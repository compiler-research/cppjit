"""Turn the benchmarks' callgrind counts into results and reports.

collect: read the dumps of a callgrind.sh run into a results JSON:
         {"benchmarks": {test name: instructions}, "commit": ...,
          "fingerprint": ...}.
compare: compare head's results against base's, write a markdown report
         (the PR comment) and exit 1 when a benchmark got slower than the
         threshold allows.
export:  convert results to github-action-benchmark's customSmallerIsBetter
         format, one file per kind of call.
"""

import argparse
import glob
import json
import math
import os
import sys
from collections.abc import Callable
from typing import Any

# kind, group, case, instructions
Benchmark = tuple[str, str, str, int]
# kind, group, case, base's instructions, head's, head/base
Row = tuple[str, str, str, int, int, float]

KINDS = ("first_call", "successive_call")
SHORT = {"first_call": "first", "successive_call": "hot"}
TRIGGER = "desc: Trigger: Client Request: "


def collect(args: argparse.Namespace) -> int:
    counts: dict[str, int] = {}
    for path in glob.glob(os.path.join(args.dumps, "callgrind.out*")):
        name: str | None = None
        total: int | None = None
        with open(path) as f:
            for line in f:
                if line.startswith(TRIGGER):
                    name = line[len(TRIGGER) :].rstrip("\n")
                elif line.startswith(("totals:", "summary:")):
                    total = int(line.split()[1])
        if name is not None and total is not None:
            counts[name] = total
    baseline = counts.pop("baseline", None)
    if baseline is None or not counts:
        sys.exit("%s has no benchmark dumps; did callgrind run?" % args.dumps)
    results = {
        "commit": args.commit,
        "fingerprint": args.fingerprint,
        "benchmarks": {k: max(v - baseline, 0) for k, v in sorted(counts.items())},
    }
    with open(args.output, "w") as f:
        json.dump(results, f, indent=1)
    return 0


def load(path: str) -> tuple[dict[str, Any], dict[str, Benchmark]]:
    """The results and {name: (kind, group, case, count)} of their benchmarks."""

    with open(path) as f:
        results = json.load(f)
    benchmarks: dict[str, Benchmark] = {}
    for name, count in results["benchmarks"].items():
        # name is test_<kind>[<group>/<case>]
        test, _, param = name.partition("[")
        group, _, case = param[:-1].partition("/")
        benchmarks[name] = (test[len("test_") :], group, case, count)
    return results, benchmarks


def fmt_count(n: float) -> str:
    for scale, suffix in ((1e9, " G"), (1e6, " M"), (1e3, " k")):
        if n >= scale:
            return "%.4g%s" % (n / scale, suffix)
    return "%d" % n


def fmt_change(ratio: float) -> str:
    return "%+.2f%%" % ((ratio - 1) * 100)


def geomean(values: list[int]) -> float:
    # a count can be 0 when a call costs no more than the markers
    return math.exp(sum(math.log(max(v, 1)) for v in values) / len(values))


def compare(args: argparse.Namespace) -> int:
    base_results, base = load(args.base)
    head_results, head = load(args.head)
    limit = 1 + args.threshold / 100
    rows: list[Row] = []
    for name in sorted(set(base) & set(head)):
        kind, group, case, b = base[name]
        h = head[name][3]
        rows.append((kind, group, case, b, h, max(h, 1) / max(b, 1)))
    slower = [r for r in rows if r[5] > limit]
    faster = [r for r in rows if r[5] < 1 / limit]
    added = sorted(set(head) - set(base))
    removed = sorted(set(base) - set(head))

    base_label = "`%s`" % args.base_name
    head_label = "`%s`" % args.head_name

    out = ["<!-- cppjit-benchmark -->", "## Benchmark Report"]
    if slower:
        out.append(
            ":x: %d of %d benchmarks run more than %g%% more instructions "
            "than %s." % (len(slower), len(rows), args.threshold, base_label)
        )
    else:
        out.append(
            ":white_check_mark: No benchmark runs more than %g%% more "
            "instructions than %s." % (args.threshold, base_label)
        )
    base_sha = base_results.get("commit")
    head_sha = head_results.get("commit")
    if base_sha and head_sha:
        url = "%s/commit/" % args.repo_url if args.repo_url else None

        def commit(sha: str) -> str:
            return "[`%s`](%s%s)" % (sha[:7], url, sha) if url else "`%s`" % sha[:7]

        out.append(
            "Comparing base (%s) to head (%s), in instructions counted by "
            "callgrind." % (commit(base_sha), commit(head_sha))
        )
    if args.note:
        out.append(args.note)
    if args.charts_url:
        out.append("History of `main`: [benchmark charts](%s)." % args.charts_url)
    out.append("")

    # codecov-style summary: one line per kind and group with the geometric
    # mean of its counts; '-' marks a regression and '+' an improvement
    def line(sign: str, label: str, b: str, h: str, change: str) -> str:
        return "%s %-26s%11s%11s%10s" % (sign, label, b, h, change)

    width = len(line(" ", "", "", "", ""))
    out += [
        "```diff",
        "@@%s@@" % " Benchmark Diff (geomean) ".center(width - 4),
        "##%25s%11s%11s%8s ##" % ("", args.base_name[:10], args.head_name[:10], "+/-"),
        "=" * width,
    ]
    for kind in KINDS:
        for group in sorted({r[1] for r in rows if r[0] == kind}):
            sel = [r for r in rows if r[0] == kind and r[1] == group]
            base_mean = geomean([r[3] for r in sel])
            head_mean = geomean([r[4] for r in sel])
            ratio = head_mean / base_mean
            sign = "-" if ratio > limit else "+" if ratio < 1 / limit else " "
            label = "%s/%s" % (SHORT[kind], group)
            out.append(
                line(
                    sign,
                    label,
                    fmt_count(base_mean),
                    fmt_count(head_mean),
                    fmt_change(ratio),
                )
            )
    out.append("=" * width)
    out.append(line("-", "Slower", "", "", str(len(slower))))
    out.append(line("+", "Faster", "", "", str(len(faster))))
    unchanged = len(rows) - len(slower) - len(faster)
    out.append(line(" ", "Unchanged", "", "", str(unchanged)))
    if added:
        out.append(line(" ", "New", "", "", str(len(added))))
    if removed:
        out.append(line(" ", "Removed", "", "", str(len(removed))))
    out += ["```", ""]

    def table(selected: list[Row]) -> list[str]:
        lines = [
            "| Benchmark | %s | %s | Δ | |" % (base_label, head_label),
            "|---|---:|---:|---:|---|",
        ]
        for kind, group, case, b, h, ratio in selected:
            mark = ":x:" if ratio > limit else ":rocket:" if ratio < 1 / limit else ""
            lines.append(
                "| %s/%s/`%s` | %s | %s | `%s` | %s |"
                % (
                    SHORT[kind],
                    group,
                    case,
                    fmt_count(b),
                    fmt_count(h),
                    fmt_change(ratio),
                    mark,
                )
            )
        return lines

    changed = sorted(slower, key=lambda r: -r[5]) + sorted(faster, key=lambda r: r[5])
    if changed:
        out += table(changed) + [""]
    out += ["<details><summary>All benchmarks</summary>", ""]
    out += table(rows)
    for name in added:
        out.append("| `%s` | | %s | new | |" % (name, fmt_count(head[name][3])))
    for name in removed:
        out.append("| `%s` | %s | | removed | |" % (name, fmt_count(base[name][3])))
    out += ["", "</details>", ""]

    report = "\n".join(out)
    if args.markdown:
        with open(args.markdown, "w") as f:
            f.write(report)
    else:
        print(report)
    return 1 if slower else 0


def export(args: argparse.Namespace) -> int:
    _, benchmarks = load(args.results)
    for kind in KINDS:
        data = [
            {"name": "%s/%s" % (group, case), "unit": "instructions", "value": n}
            for k, group, case, n in sorted(benchmarks.values())
            if k == kind
        ]
        with open(getattr(args, kind), "w") as f:
            json.dump(data, f, indent=1)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect", help="callgrind dumps to results")
    p.add_argument("dumps", help="directory of callgrind.out* files")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--commit", help="the measured commit, for the report")
    p.add_argument(
        "--fingerprint",
        help="the toolchain and environment; counts compare only within one",
    )
    p.set_defaults(func=collect)

    p = sub.add_parser("compare", help="compare head against base")
    p.add_argument("--base", required=True, metavar="JSON")
    p.add_argument("--head", required=True, metavar="JSON")
    p.add_argument("--threshold", type=float, default=5.0, help="percent")
    p.add_argument("--base-name", default="main")
    p.add_argument("--head-name", default="head")
    p.add_argument("--repo-url", help="for commit links")
    p.add_argument("--charts-url")
    p.add_argument("--note", help="a line to add under the summary")
    p.add_argument("--markdown", help="write the report here, not to stdout")
    p.set_defaults(func=compare)

    p = sub.add_parser("export", help="github-action-benchmark input")
    p.add_argument("results", metavar="JSON")
    for kind in KINDS:
        p.add_argument("--" + kind.replace("_", "-"), dest=kind, required=True)
    p.set_defaults(func=export)

    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
