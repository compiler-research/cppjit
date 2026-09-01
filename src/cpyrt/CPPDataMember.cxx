// Bindings
#include "cpyrt.h"

using namespace cppjit;
#include "CPPDataMember.h"
#include "CPPEnum.h"
#include "CPPInstance.h"
#include "Dimensions.h"
#include "LowLevelViews.h"
#include "ProxyWrappers.h"
#include "PyStrings.h"
#include "TypeManip.h"
#include "Utility.h"
#include "cppjit_interop.h"
#include "cpyrt/Reflex.h"

// Standard
#include <algorithm>
#include <cstring>
#include <limits.h>
#include <structmember.h>
#include <vector>

#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)
#error "cpyrt bit-field access assumes a little-endian byte order"
#endif

// Not conditional on the target's pointer width: "unsigned long long x : 64"
// is legal on a 32-bit target too, so a 9-byte span is reachable everywhere
// and a 64-bit accumulator is never sufficient.
#if !defined(__SIZEOF_INT128__)
#error "cpyrt bit-field access needs unsigned __int128 (a bit-field span can \
reach 9 bytes); no MSVC/32-bit fallback is implemented"
#endif

namespace cppjit::cpyrt {

// Byte span a bit-field occupies, derived from (bit offset, bit width) --
// never from the declared type's width, which would over-read a packed
// struct's trailing member. Preconditions, enforced in Set(): fBitWidth is
// in [1,64], so nbytes is in [1,9] and always fits the 16-byte accumulator.
struct BitFieldSpan {
  int shift;              // bit position within the first byte, 0..7
  int nbytes;             // bytes to read/write, 1..9
  unsigned __int128 mask; // fBitWidth low bits set
};

static inline BitFieldSpan bitfield_span(intptr_t bit_offset, int bit_width) {
  BitFieldSpan s;
  s.shift = (int)(bit_offset % 8);
  s.nbytes = (s.shift + bit_width + 7) / 8;
  s.mask = ((unsigned __int128)1 << bit_width) - 1;
  return s;
}

enum ETypeDetails {
  kNone = 0x0000,
  kIsStaticData = 0x0001,
  kIsConstData = 0x0002,
  kIsArrayType = 0x0004,
  kIsEnumPrep = 0x0008,
  kIsEnumType = 0x0010,
  kIsCachable = 0x0020,
  kIsBitField = 0x0040,
  kIsSignedBitField = 0x0080,
  kIsBoolBitField = 0x0100
};

//= cpyrt data member as Python property behavior =========================
static PyObject* dm_get(CPPDataMember* dm, CPPInstance* pyobj,
                        PyObject* /* kls */) {
  // cache lookup for low level views
  if (pyobj && dm->fFlags & kIsCachable) {
    cpyrt::CI_DatamemberCache_t& cache = pyobj->GetDatamemberCache();
    for (auto it = cache.begin(); it != cache.end(); ++it) {
      if (it->first == dm->fOffset) {
        if (it->second) {
          Py_INCREF(it->second);
          return it->second;
        } else
          cache.erase(it);
        break;
      }
    }
  }

  if (dm->fFlags & (kIsEnumPrep | kIsEnumType)) {
    if (dm->fFlags & kIsEnumPrep) {
      // still need to do lookup; only ever try this once, then fallback on
      // converter
      dm->fFlags &= ~kIsEnumPrep;

      // fDescription contains the full name of the actual enum value object
      const interop::TCppScope_t enum_type =
          interop::GetParentScope(dm->fScope);
      const interop::TCppScope_t enum_scope =
          interop::GetParentScope(enum_type);

      PyObject* pyscope = CreateScopeProxy(enum_scope);
      if (pyscope) {
        PyObject* pyEnumType = PyObject_GetAttrString(
            pyscope, interop::GetFinalName(enum_type).c_str());
        if (pyEnumType) {
          PyObject* pyval = PyObject_GetAttrString(
              pyEnumType, interop::GetFinalName(dm->fScope).c_str());
          Py_DECREF(pyEnumType);
          if (pyval) {
            Py_DECREF(dm->fDescription);
            dm->fDescription = pyval;
            dm->fFlags |= kIsEnumType;
          }
        }
        Py_DECREF(pyscope);
      }
      if (!(dm->fFlags & kIsEnumType))
        PyErr_Clear();
    }

    if (dm->fFlags & kIsEnumType) {
      Py_INCREF(dm->fDescription);
      return dm->fDescription;
    }

    if (interop::IsEnumConstant(dm->fScope)) {
      // anonymous enum
      return pyval_from_enum(interop::ResolveEnum(dm->fScope), nullptr, nullptr,
                             dm->fScope);
    }
  }
  // non-initialized or public data accesses through class (e.g. by help())
  void* address = dm->GetAddress(pyobj);
  if (!address || (intptr_t)address == -1 /* Cling error */)
    return nullptr;

  if (dm->fFlags & kIsBitField) {
    // Read only the bytes this field actually occupies: never the declared
    // type's width, which is unknowable from the type name and would
    // over-read a packed struct's last member.
    const BitFieldSpan span = bitfield_span(dm->fBitOffset, dm->fBitWidth);
    unsigned __int128 word = 0;
    std::memcpy(&word, address, (size_t)span.nbytes);

    const unsigned __int128 extracted = (word >> span.shift) & span.mask;

    if (dm->fFlags & kIsBoolBitField)
      return PyBool_FromLong((long)(extracted != 0));

    if (dm->fFlags & kIsSignedBitField) {
      // sign-extend from fBitWidth; fBitWidth > 0 is enforced in Set(), so
      // this shift amount is never negative.
      const unsigned __int128 one = 1;
      const unsigned __int128 sign_bit = one << (dm->fBitWidth - 1);
      if (extracted & sign_bit) {
        const long long sval =
            (long long)(extracted | ~(span.mask)); // fill above with 1s
        return PyLong_FromLongLong(sval);
      }
      return PyLong_FromLongLong((long long)extracted);
    }
    return PyLong_FromUnsignedLongLong((unsigned long long)extracted);
  }

  if (dm->fConverter != 0) {
    PyObject* result = dm->fConverter->FromMemory(
        (dm->fFlags & kIsArrayType) ? &address : address);
    if (!result)
      return result;

    // low level views are expensive to create, so cache them on the object
    // instead
    bool isLLView = LowLevelView_CheckExact(result);
    if (isLLView && CPPInstance_Check(pyobj)) {
      Py_INCREF(result);
      pyobj->GetDatamemberCache().push_back(
          std::make_pair(dm->fOffset, result));
      dm->fFlags |= kIsCachable;
    }

    // ensure that the encapsulating class does not go away for the duration
    // of the data member's lifetime, if it is a bound type (it doesn't matter
    // for builtin types, b/c those are copied over into python types and thus
    // end up being "stand-alone")
    // TODO: should be done for LLViews as well
    else if (pyobj && !(dm->fFlags & kIsStaticData) &&
             CPPInstance_Check(result)) {
      if (PyObject_SetAttr(result, PyStrings::gLifeLine, (PyObject*)pyobj) ==
          -1)
        PyErr_Clear(); // ignored
    }

    return result;
  }

  PyErr_Format(PyExc_NotImplementedError, "no converter available for \"%s\"",
               dm->GetName().c_str());
  return nullptr;
}

//-----------------------------------------------------------------------------
static int dm_set(CPPDataMember* dm, CPPInstance* pyobj, PyObject* value) {
  // Set the value of the C++ datum held.
  const int errret = -1;

  if (!value) {
    // we're being deleted; fine for namespaces (redo lookup next time), but
    // makes no sense for classes/structs
    if (!interop::IsNamespace(dm->fEnclosingScope)) {
      PyErr_SetString(PyExc_TypeError, "data member deletion is not supported");
      return errret;
    }

    // deletion removes the proxy, with the idea that a fresh lookup can be
    // made, to support Cling's shadowing of declarations (TODO: the use case
    // here is redeclared variables, for which fDescription is indeed th ename;
    // it might fail for enums).
    return PyObject_DelAttr((PyObject*)Py_TYPE(pyobj), dm->fDescription);
  }

  // filter const objects to prevent changing their values
  if (dm->fFlags & kIsConstData) {
    PyErr_SetString(PyExc_TypeError, "assignment to const data not allowed");
    return errret;
  }

  // remove cached low level view, if any (will be restored upon reaeding)
  if (dm->fFlags & kIsCachable) {
    cpyrt::CI_DatamemberCache_t& cache = pyobj->GetDatamemberCache();
    for (auto it = cache.begin(); it != cache.end(); ++it) {
      if (it->first == dm->fOffset) {
        Py_XDECREF(it->second);
        cache.erase(it);
        break;
      }
    }
  }

  intptr_t address = (intptr_t)dm->GetAddress(pyobj);
  if (!address || address == -1 /* Cling error */)
    return errret;

  if (dm->fFlags & kIsBitField) {
    if (dm->fFlags & kIsBoolBitField) {
      // Mirror cpyrt_PyLong_AsBool in Converters.cxx exactly: a bool
      // member accepts only a bool or the integers 0 and 1, and a float is
      // rejected outright even where it would convert. A PyLong_AsLong
      // failure returns -1, which is neither 0 nor 1, so it falls into the
      // same ValueError -- deliberately replacing the original TypeError or
      // OverflowError, so a bit-field reports precisely what a non-bit-field
      // bool member reports.
      if (!PyBool_Check(value)) {
        const long as_long = PyLong_AsLong(value);
        if (!(as_long == 0 || as_long == 1) || PyFloat_Check(value)) {
          PyErr_SetString(PyExc_ValueError,
                          "boolean value should be bool, or integer 1 or 0");
          return errret;
        }
      }
    }

    // Documented divergence from the non-bit-field path, not an oversight: the
    // ...Mask conversion truncates out-of-range values silently, so "bf : 4 =
    // -1" stores 15 and "bf : 4 = 2**100" stores 0, where the same assignment
    // to a plain "unsigned" member raises ValueError. Truncation of a negative
    // is ordinary C++ bit-field behaviour and test04 codifies it; the 2**100
    // case discards an error Python would otherwise report. Kept as-is because
    // masking is what the stored width means, and range-checking here would
    // have to pick a signedness the declared type does not settle.
    //
    // Clearing first is what makes the failure test below trustworthy: the
    // sentinel (unsigned long long)-1 is also a legitimate result (that is
    // exactly what "= -1" masks to), so a stale error set before dm_set was
    // entered would otherwise turn a valid write into a spurious failure.
    // Same reasoning as the stale-error handling in CPPScope.cxx.
    PyErr_Clear();
    const unsigned long long raw = PyLong_AsUnsignedLongLongMask(value);
    if (raw == (unsigned long long)-1 && PyErr_Occurred())
      return errret;

    // fBitWidth is in [1, 64] here -- Set() only sets kIsBitField under that
    // precondition -- so bitfield_span's shift is always well-defined; no
    // need to guard against a 128-bit field.
    const BitFieldSpan span = bitfield_span(dm->fBitOffset, dm->fBitWidth);

    // read-modify-write, so sibling bit-fields sharing these bytes survive
    unsigned __int128 word = 0;
    std::memcpy(&word, (void*)address, (size_t)span.nbytes);
    word &= ~(span.mask << span.shift);
    word |= ((unsigned __int128)raw & span.mask) << span.shift;
    std::memcpy((void*)address, &word, (size_t)span.nbytes);
    return 0;
  }

  // for fixed size arrays
  void* ptr = (void*)address;
  if (dm->fFlags & kIsArrayType)
    ptr = &address;

  // actual conversion; return on success
  if (dm->fConverter && dm->fConverter->ToMemory(value, ptr, (PyObject*)pyobj))
    return 0;

  // set a python error, if not already done
  if (!PyErr_Occurred())
    PyErr_SetString(PyExc_RuntimeError,
                    "property type mismatch or assignment not allowed");

  // failure ...
  return errret;
}

//= cpyrt data member construction/destruction ===========================
static CPPDataMember* dm_new(PyTypeObject* pytype, PyObject*, PyObject*) {
  // Create and initialize a new property descriptor.
  CPPDataMember* dm = (CPPDataMember*)pytype->tp_alloc(pytype, 0);

  dm->fOffset = 0;
  dm->fFlags = 0;
  dm->fConverter = nullptr;
  dm->fEnclosingScope = nullptr;
  dm->fDescription = nullptr;
  dm->fDoc = nullptr;
  dm->fBitOffset = 0;
  dm->fBitWidth = 0;

  new (&dm->fFullType) std::string{};

  return dm;
}

//----------------------------------------------------------------------------
static void dm_dealloc(CPPDataMember* dm) {
  // Deallocate memory held by this descriptor.
  using namespace std;
  if (dm->fConverter && dm->fConverter->HasState())
    delete dm->fConverter;
  Py_XDECREF(dm->fDescription); // never exposed so no GC necessary
  Py_XDECREF(dm->fDoc);

  dm->fFullType.~string();

  Py_TYPE(dm)->tp_free((PyObject*)dm);
}

static PyMemberDef dm_members[] = {
    {(char*)"__doc__", T_OBJECT, offsetof(CPPDataMember, fDoc), 0,
     (char*)"writable documentation"},
    {NULL, 0, 0, 0, nullptr} /* Sentinel */
};

//= cpyrt datamember proxy access to internals ============================
static PyObject* dm_reflex(CPPDataMember* dm, PyObject* args) {
  // Provide the requested reflection information.
  interop::Reflex::RequestId_t request = -1;
  interop::Reflex::FormatId_t format = interop::Reflex::OPTIMAL;
  if (!PyArg_ParseTuple(args, const_cast<char*>("i|i:__cpp_reflex__"), &request,
                        &format))
    return nullptr;

  if (request == interop::Reflex::TYPE) {
    if (format == interop::Reflex::OPTIMAL ||
        format == interop::Reflex::AS_STRING)
      return cpyrt_PyText_FromString(dm->fFullType.c_str());
  } else if (request == interop::Reflex::OFFSET) {
    if (format == interop::Reflex::OPTIMAL)
      return PyLong_FromLong(dm->fOffset);
  }

  PyErr_Format(PyExc_ValueError, "unsupported reflex request %d or format %d",
               request, format);
  return nullptr;
}

//----------------------------------------------------------------------------
static PyMethodDef dm_methods[] = {
    {(char*)"__cpp_reflex__", (PyCFunction)dm_reflex, METH_VARARGS,
     (char*)"C++ datamember reflection information"},
    {(char*)nullptr, nullptr, 0, nullptr}};

//= cpyrt data member type ================================================
PyTypeObject CPPDataMember_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type,
                          0)(char*) "cppjit.CPPDataMember", // tp_name
    sizeof(CPPDataMember),                                  // tp_basicsize
    0,                                                      // tp_itemsize
    (destructor)dm_dealloc,                                 // tp_dealloc
    0,                                      // tp_vectorcall_offset / tp_print
    0,                                      // tp_getattr
    0,                                      // tp_setattr
    0,                                      // tp_as_async / tp_compare
    0,                                      // tp_repr
    0,                                      // tp_as_number
    0,                                      // tp_as_sequence
    0,                                      // tp_as_mapping
    0,                                      // tp_hash
    0,                                      // tp_call
    0,                                      // tp_str
    0,                                      // tp_getattro
    0,                                      // tp_setattro
    0,                                      // tp_as_buffer
    Py_TPFLAGS_DEFAULT,                     // tp_flags
    (char*)"cppjit data member (internal)", // tp_doc
    0,                                      // tp_traverse
    0,                                      // tp_clear
    0,                                      // tp_richcompare
    0,                                      // tp_weaklistoffset
    0,                                      // tp_iter
    0,                                      // tp_iternext
    dm_methods,                             // tp_methods
    dm_members,                             // tp_members
    0,                                      // tp_getset
    0,                                      // tp_base
    0,                                      // tp_dict
    (descrgetfunc)dm_get,                   // tp_descr_get
    (descrsetfunc)dm_set,                   // tp_descr_set
    0,                                      // tp_dictoffset
    0,                                      // tp_init
    0,                                      // tp_alloc
    (newfunc)dm_new,                        // tp_new
    0,                                      // tp_free
    0,                                      // tp_is_gc
    0,                                      // tp_bases
    0,                                      // tp_mro
    0,                                      // tp_cache
    0,                                      // tp_subclasses
    0,                                      // tp_weaklist
    0,                                      // tp_del
    0,                                      // tp_version_tag
    0,                                      // tp_finalize
    0                                       // tp_vectorcall
    CPYRT_PYTYPE_TAIL};

} // namespace cppjit::cpyrt

//- public members -----------------------------------------------------------
void cpyrt::CPPDataMember::Set(interop::TCppScope_t scope,
                               interop::TCppScope_t data) {
  if (interop::IsLambdaClass(interop::GetDatamemberType(data))) {
    fScope = interop::WrapLambdaFromVariable(data);
  } else {
    fScope = data;
  }

  fEnclosingScope = scope;
  const interop::TCppScope_t offset_parent =
      fScope == data ? scope : interop::GetScope("__cppjit_internal_wrap_g");
  fOffset = interop::GetDatamemberOffset(fScope, offset_parent);
  fFlags = interop::IsStaticDatamember(fScope) ? kIsStaticData : 0;

  const std::string name = interop::GetFinalName(fScope);
  interop::TCppType_t type;

  if (interop::IsEnumConstant(fScope)) {
    type = interop::GetEnumConstantType(fScope);
    fFullType = interop::GetTypeAsString(type);
    if (fFullType.find("(anonymous)") == std::string::npos &&
        fFullType.find("(unnamed)") == std::string::npos) {
      // repurpose fDescription for lazy lookup of the enum later
      fDescription = cpyrt_PyText_FromString((fFullType + "::" + name).c_str());
      fFlags |= kIsEnumPrep;
    }
    type = interop::ResolveType(type);
    fFlags |= kIsConstData;
  } else {
    type = interop::GetDatamemberType(fScope);
    fFullType = interop::GetTypeAsString(type);

    // Get the integer type if it's an enum
    if (interop::IsEnumType(type))
      type = interop::ResolveType(type);

    if (interop::IsConstVar(fScope))
      fFlags |= kIsConstData;
  }

  // Bit-fields need masked access: cache the layout facts once here so the
  // attribute-access path never has to take the interop lock. A bit-field is
  // never static, so fOffset is a genuine byte offset.
  if (!(fFlags & kIsStaticData) && interop::IsBitFieldDatamember(fScope)) {
    const intptr_t bit_offset =
        interop::GetDatamemberBitOffset(fScope, offset_parent);
    const int bit_width = interop::GetDatamemberBitWidth(fScope);
    // Cap at 64 bits: dm_get's memcpy destination is a 16-byte
    // unsigned __int128, and nbytes = ceil((shift + bit_width) / 8) with
    // shift in [0, 7] needs bit_width <= 64 to stay within 9 bytes <= 16.
    // Gating on width alone (rather than shift + bit_width <= 128) also
    // rules out an unpacked "unsigned __int128 x : 128" (shift == 0, so
    // that inequality would pass) whose 64-bit extraction would otherwise
    // silently truncate. A wider bit-field leaves kIsBitField unset and
    // falls through to fConverter, whose base Converter::FromMemory has no
    // override for __int128 and raises a clean TypeError -- the
    // pre-existing behaviour.
    //
    // The fOffset == bit_offset / 8 term is the invariant dm_get's masked
    // access rests on, checked rather than asserted: it must hold by
    // construction, since Cpp::GetVariableBitOffset is defined as
    // GetVariableOffset(var, parent) * 8 + getFieldOffset(FD) % 8, so the
    // byte offset is baked into the bit offset's high bits for any
    // non-negative result. But an assert is compiled out of the Release
    // builds this ships as, and if a future CppInterOp change ever
    // desynchronises the two the failure mode is a garbage read at a valid
    // address -- silent wrong data, not a crash. Declining to treat the
    // member as a bit-field instead falls back to the pre-existing
    // converter path, which is merely wrong for packed layouts rather than
    // arbitrary. One compare per descriptor construction, not per access.
    if (bit_offset >= 0 && bit_width > 0 && bit_width <= 64 &&
        fOffset == bit_offset / 8) {
      fFlags |= kIsBitField;
      fBitOffset = bit_offset;
      fBitWidth = bit_width;

      // Name-based, unlike everything else here: there is no IsBoolType
      // query, and IsIntegerType reports bool as an unsigned integer. Exact
      // match (not a substring search) is deliberate: a substring search
      // would also fire on a typedef like "bool_flags_t" that merely
      // contains "bool", turning an integer into True/False. The trade-off
      // is the opposite direction -- a bit-field declared through a
      // typedef *of* bool still reads back as 0/1 rather than True/False --
      // a presentation difference, not a wrong value.
      //
      // No equivalent flag exists for char, and that is a real, documented
      // divergence: a plain "char c" member goes through CharConverter and
      // reads back as a one-character Python str ('A'), while "char c : 5"
      // takes the masked path here and reads back an int (-3 for the bits
      // 0b11101). signed char and unsigned char bit-fields diverge the same
      // way -- int rather than str, unsigned char merely not sign-extending.
      // Only bool was given parity; char keeps the integer presentation.
      if (fFullType == "bool")
        fFlags |= kIsBoolBitField;

      bool is_signed = false;
      if (interop::IsIntegerType(type, &is_signed) && is_signed)
        fFlags |= kIsSignedBitField;
    }
  }

  auto ldims = interop::GetDimensions(type);
  std::vector<dim_t> dims(ldims.begin(), ldims.end());

  if (!dims.empty())
    fFlags |= kIsArrayType;

  if (dims.empty())
    fConverter = CreateConverter(type, 0);
  else
    fConverter = CreateConverter(type, {(dim_t)dims.size(), dims.data()});

  if (!(fFlags & kIsEnumPrep))
    fDescription = cpyrt_PyText_FromString(name.c_str());
}

//-----------------------------------------------------------------------------
void cpyrt::CPPDataMember::Set(interop::TCppScope_t scope,
                               const std::string& name, void* address) {
  fEnclosingScope = scope;
  fDescription = cpyrt_PyText_FromString(name.c_str());
  fOffset = (intptr_t)address;
  fFlags = kIsStaticData | kIsConstData;
  fConverter = CreateConverter("internal_enum_type_t");
  fFullType = "unsigned int";
}

//-----------------------------------------------------------------------------
void* cpyrt::CPPDataMember::GetAddress(CPPInstance* pyobj) {
  // class attributes, global properties
  if (fFlags & kIsStaticData)
    return (void*)fOffset;

  // special case: non-static lookup through class
  if (!pyobj) {
    PyErr_SetString(PyExc_AttributeError,
                    "attribute access requires an instance");
    return nullptr;
  }

  // instance attributes; requires valid object for full address
  if (!CPPInstance_Check(pyobj)) {
    PyErr_Format(PyExc_TypeError,
                 "object instance required for access to property \"%s\"",
                 GetName().c_str());
    return nullptr;
  }

  void* obj = pyobj->GetObject();
  if (!obj) {
    PyErr_SetString(PyExc_ReferenceError, "attempt to access a null-pointer");
    return nullptr;
  }

  // the proxy's internal offset is calculated from the enclosing class
  ptrdiff_t offset = 0;
  interop::TCppScope_t oisa = pyobj->ObjectIsA();
  if (oisa != fEnclosingScope)
    offset =
        interop::GetBaseOffset(oisa, fEnclosingScope, obj, 1 /* up-cast */);

  return (void*)((intptr_t)obj + offset + fOffset);
}

//-----------------------------------------------------------------------------
std::string cpyrt::CPPDataMember::GetName() {
  if (fFlags & kIsEnumType) {
    PyObject* repr = PyObject_Repr(fDescription);
    if (repr) {
      std::string res = cpyrt_PyText_AsString(repr);
      Py_DECREF(repr);
      return res;
    }
    PyErr_Clear();
    return "<unknown>";
  } else if (fFlags & kIsEnumPrep) {
    std::string fullName = cpyrt_PyText_AsString(fDescription);
    return fullName.substr(fullName.rfind("::") + 2, std::string::npos);
  }

  return cpyrt_PyText_AsString(fDescription);
}
