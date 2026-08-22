#ifndef CPYRT_CPPJIT_H
#define CPYRT_CPPJIT_H

// Standard
#include <set>
#include <stddef.h>
#include <stdint.h>
#include <string>
#include <vector>

// import/export (after precommondefs.h from PyPy)
#ifdef _MSC_VER
#define CPPJIT_IMPORT extern __declspec(dllimport)
#else
#define CPPJIT_IMPORT extern
#endif

// some more types; assumes cppjit_interop.h follows Python.h
#ifndef PY_LONG_LONG
#ifdef _WIN32
typedef __int64 PY_LONG_LONG;
#else
typedef long long PY_LONG_LONG;
#endif
#endif

#ifndef PY_ULONG_LONG
#ifdef _WIN32
typedef unsigned __int64 PY_ULONG_LONG;
#else
typedef unsigned long long PY_ULONG_LONG;
#endif
#endif

#ifndef PY_LONG_DOUBLE
typedef long double PY_LONG_DOUBLE;
#endif

// FIXME: We should not duplicate these definitions here and in CppInterOp.h
// The current setup relies on finding an identical symbol definition in
// libcppjitbackend.so which is fragile and requires updating both locations
// when changing. Ideally we should have the ability to set/get the template arg
// info provided through some factory methods in CppInterOp API, so the clients
// can rely completely on opaque pointers like we do for the rest of the
// argument types.
struct TemplateArgInfo {
  void* m_Type;
  const char* m_IntegralValue;
  TemplateArgInfo(void* type, const char* integral_value = nullptr)
      : m_Type(type), m_IntegralValue(integral_value) {}
};

namespace Cpp {
using TemplateArgInfo = ::TemplateArgInfo;

struct DeclRef {
  void* data;
  DeclRef() : data(nullptr) {}
  DeclRef(void* P) : data(P) {}
  DeclRef(decltype(nullptr)) : data(nullptr) {}
  explicit operator bool() const { return data != nullptr; }
  friend bool operator==(DeclRef a, DeclRef b) { return a.data == b.data; }
  friend bool operator!=(DeclRef a, DeclRef b) { return !(a == b); }
};

struct TypeRef {
  void* data;
  TypeRef() : data(nullptr) {}
  TypeRef(void* P) : data(P) {}
  TypeRef(decltype(nullptr)) : data(nullptr) {}
  explicit operator bool() const { return data != nullptr; }
  friend bool operator==(TypeRef a, TypeRef b) { return a.data == b.data; }
  friend bool operator!=(TypeRef a, TypeRef b) { return !(a == b); }
};

struct FuncRef {
  void* data;
  FuncRef() : data(nullptr) {}
  FuncRef(void* P) : data(P) {}
  FuncRef(decltype(nullptr)) : data(nullptr) {}
  explicit operator bool() const { return data != nullptr; }
  friend bool operator==(FuncRef a, FuncRef b) { return a.data == b.data; }
  friend bool operator!=(FuncRef a, FuncRef b) { return !(a == b); }
};

struct ObjectRef {
  void* data;
  ObjectRef() : data(nullptr) {}
  ObjectRef(void* P) : data(P) {}
  ObjectRef(decltype(nullptr)) : data(nullptr) {}
  explicit operator bool() const { return data != nullptr; }
  friend bool operator==(ObjectRef a, ObjectRef b) { return a.data == b.data; }
  friend bool operator!=(ObjectRef a, ObjectRef b) { return !(a == b); }
};
} // namespace Cpp

template <> struct std::hash<Cpp::DeclRef> {
  std::size_t operator()(const Cpp::DeclRef& obj) const {
    return std::hash<void*>{}(obj.data);
  }
};
template <> struct std::hash<Cpp::TypeRef> {
  std::size_t operator()(const Cpp::TypeRef& obj) const {
    return std::hash<void*>{}(obj.data);
  }
};
template <> struct std::hash<Cpp::FuncRef> {
  std::size_t operator()(const Cpp::FuncRef& obj) const {
    return std::hash<void*>{}(obj.data);
  }
};
template <> struct std::hash<Cpp::ObjectRef> {
  std::size_t operator()(const Cpp::ObjectRef& obj) const {
    return std::hash<void*>{}(obj.data);
  }
};

namespace cppjit::interop {
typedef Cpp::DeclRef TCppScope_t;
typedef Cpp::TypeRef TCppType_t;
typedef Cpp::ObjectRef TCppObject_t;
typedef Cpp::FuncRef TCppMethod_t;
typedef size_t TCppIndex_t;
typedef void* TCppFuncAddr_t;

// direct interpreter access -------------------------------------------------
CPPJIT_IMPORT
bool Compile(const std::string& code, bool silent = false);
CPPJIT_IMPORT
std::string ToString(TCppScope_t klass, TCppObject_t obj);

// name to opaque C++ scope representation -----------------------------------
CPPJIT_IMPORT
std::string ResolveName(const std::string& cppitem_name);
CPPJIT_IMPORT
TCppType_t ResolveType(TCppType_t cppitem_name);
CPPJIT_IMPORT
TCppType_t ResolveEnumReferenceType(TCppType_t type);
CPPJIT_IMPORT
TCppType_t ResolveEnumPointerType(TCppType_t type);
CPPJIT_IMPORT
TCppType_t GetRealType(TCppType_t type);
CPPJIT_IMPORT
TCppType_t GetPointerType(TCppType_t type);
CPPJIT_IMPORT
TCppType_t GetReferencedType(TCppType_t type, bool rvalue = false);
CPPJIT_IMPORT
std::string ResolveEnum(TCppScope_t enum_scope);
CPPJIT_IMPORT
bool IsLValueReferenceType(TCppType_t type);
CPPJIT_IMPORT
bool IsRValueReferenceType(TCppType_t type);
CPPJIT_IMPORT
bool IsClassType(TCppType_t type);
CPPJIT_IMPORT
bool IsIntegerType(TCppType_t type, bool* is_signed = nullptr);
CPPJIT_IMPORT
bool IsPointerType(TCppType_t type);
CPPJIT_IMPORT
bool IsFunctionPointerType(TCppType_t type);
CPPJIT_IMPORT
TCppType_t GetType(const std::string& name, bool enable_slow_lookup = false);
CPPJIT_IMPORT
bool AppendTypesSlow(const std::string& name,
                     std::vector<Cpp::TemplateArgInfo>& types,
                     interop::TCppScope_t parent = nullptr);
CPPJIT_IMPORT
TCppType_t GetComplexType(const std::string& element_type);
CPPJIT_IMPORT
TCppScope_t GetScope(const std::string& scope_name,
                     TCppScope_t parent_scope = TCppScope_t{});
CPPJIT_IMPORT
TCppScope_t GetUnderlyingScope(TCppScope_t scope);
CPPJIT_IMPORT
TCppScope_t GetFullScope(const std::string& scope_name);
CPPJIT_IMPORT
TCppScope_t GetTypeScope(TCppScope_t klass);
CPPJIT_IMPORT
TCppScope_t GetNamed(const std::string& scope_name,
                     TCppScope_t parent_scope = TCppScope_t{});
CPPJIT_IMPORT
TCppScope_t GetParentScope(TCppScope_t scope);
CPPJIT_IMPORT
TCppScope_t GetScopeFromType(TCppType_t type);
CPPJIT_IMPORT
TCppType_t GetTypeFromScope(TCppScope_t klass);
CPPJIT_IMPORT
TCppScope_t GetGlobalScope();
CPPJIT_IMPORT
TCppScope_t GetActualClass(TCppScope_t klass, TCppObject_t obj);
CPPJIT_IMPORT
size_t SizeOf(TCppScope_t klass);
CPPJIT_IMPORT
size_t SizeOfType(TCppType_t type);

CPPJIT_IMPORT
bool IsBuiltin(const std::string& type_name);

CPPJIT_IMPORT
bool IsBuiltin(TCppType_t type);

CPPJIT_IMPORT
bool IsComplete(TCppScope_t type);

// memory management ---------------------------------------------------------
CPPJIT_IMPORT
TCppObject_t Allocate(TCppScope_t scope);
CPPJIT_IMPORT
void Deallocate(TCppScope_t scope, TCppObject_t instance);
CPPJIT_IMPORT
TCppObject_t Construct(TCppScope_t scope, void* arena = nullptr);
CPPJIT_IMPORT
void Destruct(TCppScope_t scope, TCppObject_t instance);

// method/function dispatching -----------------------------------------------
CPPJIT_IMPORT
void CallV(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
unsigned char CallB(TCppMethod_t method, TCppObject_t self, size_t nargs,
                    void* args);
CPPJIT_IMPORT
char CallC(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
short CallH(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
int CallI(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
long CallL(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
PY_LONG_LONG CallLL(TCppMethod_t method, TCppObject_t self, size_t nargs,
                    void* args);
CPPJIT_IMPORT
float CallF(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
double CallD(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
PY_LONG_DOUBLE CallLD(TCppMethod_t method, TCppObject_t self, size_t nargs,
                      void* args);

CPPJIT_IMPORT
void* CallR(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args);
CPPJIT_IMPORT
char* CallS(TCppMethod_t method, TCppObject_t self, size_t nargs, void* args,
            size_t* length);
CPPJIT_IMPORT
TCppObject_t CallConstructor(TCppMethod_t method, TCppScope_t klass,
                             size_t nargs, void* args);
CPPJIT_IMPORT
void CallDestructor(TCppScope_t type, TCppObject_t self);
CPPJIT_IMPORT
TCppObject_t CallO(TCppMethod_t method, TCppObject_t self, size_t nargs,
                   void* args, TCppType_t result_type);

CPPJIT_IMPORT
TCppFuncAddr_t GetFunctionAddress(TCppMethod_t method,
                                  bool check_enabled = true);

// handling of function argument buffer --------------------------------------
CPPJIT_IMPORT
void* AllocateFunctionArgs(size_t nargs);
CPPJIT_IMPORT
void DeallocateFunctionArgs(void* args);
CPPJIT_IMPORT
size_t GetFunctionArgSizeof();
CPPJIT_IMPORT
size_t GetFunctionArgTypeoffset();

// scope reflection information ----------------------------------------------
CPPJIT_IMPORT
bool IsNamespace(TCppScope_t scope);
CPPJIT_IMPORT
bool IsClass(TCppScope_t scope);
CPPJIT_IMPORT
bool IsTemplate(TCppScope_t scope);
CPPJIT_IMPORT
bool IsTemplateInstantiation(TCppScope_t scope);
CPPJIT_IMPORT
bool IsTypedefed(TCppScope_t scope);
CPPJIT_IMPORT
bool IsAbstract(TCppScope_t scope);
CPPJIT_IMPORT
bool IsEnumScope(TCppScope_t scope);
CPPJIT_IMPORT
bool IsEnumConstant(TCppScope_t scope);
CPPJIT_IMPORT
bool IsEnumType(TCppType_t type);
CPPJIT_IMPORT
bool IsAggregate(TCppScope_t type);
CPPJIT_IMPORT
bool IsDefaultConstructable(TCppScope_t scope);
CPPJIT_IMPORT
bool IsVariable(TCppScope_t scope);

CPPJIT_IMPORT
void GetAllCppNames(TCppScope_t scope, std::set<std::string>& cppnames);

// namespace reflection information ------------------------------------------
CPPJIT_IMPORT
std::vector<interop::TCppScope_t> GetUsingNamespaces(TCppScope_t);

// class reflection information ----------------------------------------------
CPPJIT_IMPORT
std::string GetFinalName(TCppScope_t type);
CPPJIT_IMPORT
std::string GetScopedFinalName(TCppScope_t type);
CPPJIT_IMPORT
bool HasVirtualDestructor(TCppScope_t type);
CPPJIT_IMPORT
TCppIndex_t GetNumBases(TCppScope_t klass);
CPPJIT_IMPORT
TCppIndex_t GetNumBasesLongestBranch(TCppScope_t klass);
CPPJIT_IMPORT
std::string GetBaseName(TCppScope_t klass, TCppIndex_t ibase);
CPPJIT_IMPORT
TCppScope_t GetBaseScope(TCppScope_t klass, TCppIndex_t ibase);
CPPJIT_IMPORT
bool IsSubclass(TCppScope_t derived, TCppScope_t base);
CPPJIT_IMPORT
bool IsSmartPtr(TCppScope_t klass);
CPPJIT_IMPORT
bool GetSmartPtrInfo(const std::string&, TCppScope_t* raw, TCppMethod_t* deref);
// calculate offsets between declared and actual type, up-cast: direction > 0;
// down-cast: direction < 0
CPPJIT_IMPORT
ptrdiff_t GetBaseOffset(TCppScope_t derived, TCppScope_t base,
                        TCppObject_t address, int direction,
                        bool rerror = false);

// method/function reflection information ------------------------------------
CPPJIT_IMPORT
void GetClassMethods(TCppScope_t scope, std::vector<TCppMethod_t>& methods);
CPPJIT_IMPORT
std::vector<TCppMethod_t> GetMethodsFromName(TCppScope_t scope,
                                             const std::string& name);
CPPJIT_IMPORT
std::string GetName(TCppScope_t);
CPPJIT_IMPORT
std::string GetFullName(TCppScope_t);
CPPJIT_IMPORT
TCppType_t GetMethodReturnType(TCppMethod_t);
CPPJIT_IMPORT
std::string GetMethodReturnTypeAsString(TCppMethod_t);
CPPJIT_IMPORT
TCppIndex_t GetMethodNumArgs(TCppMethod_t);
CPPJIT_IMPORT
TCppIndex_t GetMethodReqArgs(TCppMethod_t);
CPPJIT_IMPORT
std::string GetMethodArgName(TCppMethod_t, TCppIndex_t iarg);
CPPJIT_IMPORT
TCppType_t GetMethodArgType(TCppMethod_t, TCppIndex_t iarg);
CPPJIT_IMPORT
TCppIndex_t CompareMethodArgType(TCppMethod_t, TCppIndex_t iarg,
                                 const std::string& req_type);
CPPJIT_IMPORT
std::string GetMethodArgTypeAsString(TCppMethod_t method, TCppIndex_t iarg);
CPPJIT_IMPORT
std::string GetMethodArgCanonTypeAsString(TCppMethod_t method,
                                          TCppIndex_t iarg);
CPPJIT_IMPORT
std::string GetMethodArgDefault(TCppMethod_t, TCppIndex_t iarg);
CPPJIT_IMPORT
std::string GetMethodSignature(TCppMethod_t, bool show_formal_args,
                               TCppIndex_t max_args = (TCppIndex_t)-1);
// GetMethodPrototype is unused.
CPPJIT_IMPORT
std::string GetMethodPrototype(TCppMethod_t, bool show_formal_args);
CPPJIT_IMPORT
std::string GetDoxygenComment(TCppScope_t scope, bool strip_markers = true);
CPPJIT_IMPORT
bool IsConstMethod(TCppMethod_t);
// Templated method/function reflection information
// ------------------------------------
CPPJIT_IMPORT
void GetTemplatedMethods(TCppScope_t scope, std::vector<TCppMethod_t>& methods);
CPPJIT_IMPORT
TCppIndex_t GetNumTemplatedMethods(TCppScope_t scope,
                                   bool accept_namespace = false);
CPPJIT_IMPORT
std::string GetTemplatedMethodName(TCppScope_t scope, TCppIndex_t imeth);
CPPJIT_IMPORT
bool ExistsMethodTemplate(TCppScope_t scope, const std::string& name);
CPPJIT_IMPORT
bool IsTemplatedMethod(TCppMethod_t method);
CPPJIT_IMPORT
bool IsStaticTemplate(TCppScope_t scope, const std::string& name);
CPPJIT_IMPORT
TCppMethod_t GetMethodTemplate(TCppScope_t scope, const std::string& name,
                               const std::string& proto);
CPPJIT_IMPORT
void GetClassOperators(interop::TCppScope_t klass, const std::string& opname,
                       std::vector<TCppMethod_t>& operators);
CPPJIT_IMPORT
TCppMethod_t GetGlobalOperator(TCppScope_t scope, const std::string& lc,
                               const std::string& rc, const std::string& op);

// method properties ---------------------------------------------------------
CPPJIT_IMPORT
bool IsDeletedMethod(TCppMethod_t method);
CPPJIT_IMPORT
bool IsPublicMethod(TCppMethod_t method);
CPPJIT_IMPORT
bool IsProtectedMethod(TCppMethod_t method);
CPPJIT_IMPORT
bool IsPrivateMethod(TCppMethod_t method);
CPPJIT_IMPORT
bool IsConstructor(TCppMethod_t method);
CPPJIT_IMPORT
bool IsDestructor(TCppMethod_t method);
CPPJIT_IMPORT
bool IsStaticMethod(TCppMethod_t method);
CPPJIT_IMPORT
bool IsExplicit(TCppMethod_t method);

// data member reflection information ----------------------------------------
CPPJIT_IMPORT
void GetDatamembers(TCppScope_t scope, std::vector<TCppScope_t>& datamembers);
CPPJIT_IMPORT
bool IsLambdaClass(TCppType_t type);
CPPJIT_IMPORT
TCppScope_t WrapLambdaFromVariable(TCppScope_t var);
CPPJIT_IMPORT
TCppMethod_t AdaptFunctionForLambdaReturn(TCppMethod_t fn);
CPPJIT_IMPORT
TCppType_t GetDatamemberType(TCppScope_t data);
CPPJIT_IMPORT
std::string GetDatamemberTypeAsString(TCppScope_t var);
CPPJIT_IMPORT
std::string GetTypeAsString(TCppType_t type);
CPPJIT_IMPORT
intptr_t GetDatamemberOffset(TCppScope_t var, TCppScope_t klass = nullptr);
CPPJIT_IMPORT
bool CheckDatamember(TCppScope_t scope, const std::string& name);

// // data member properties
// ----------------------------------------------------
CPPJIT_IMPORT
bool IsPublicData(TCppScope_t var);
CPPJIT_IMPORT
bool IsProtectedData(TCppScope_t var);
CPPJIT_IMPORT
bool IsPrivateData(TCppScope_t var);
CPPJIT_IMPORT
bool IsStaticDatamember(TCppScope_t var);
CPPJIT_IMPORT
bool IsConstVar(TCppScope_t var);
CPPJIT_IMPORT
TCppMethod_t ReduceReturnType(TCppMethod_t fn, TCppType_t reduce);
CPPJIT_IMPORT
std::vector<long int> GetDimensions(TCppType_t type);

// enum properties -----------------------------------------------------------
CPPJIT_IMPORT
std::vector<TCppScope_t> GetEnumConstants(TCppScope_t scope);
CPPJIT_IMPORT
TCppType_t GetEnumConstantType(TCppScope_t scope);
CPPJIT_IMPORT
TCppIndex_t GetEnumDataValue(TCppScope_t scope);

CPPJIT_IMPORT
TCppScope_t InstantiateTemplate(TCppScope_t tmpl, Cpp::TemplateArgInfo* args,
                                size_t args_size);

CPPJIT_IMPORT
void DumpScope(TCppScope_t scope);
} // namespace cppjit::interop

#endif // !CPYRT_CPPJIT_H
