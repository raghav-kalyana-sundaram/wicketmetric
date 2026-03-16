from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cricwarehouse", description="Wicket Metric")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull", help="Download Cricsheet register and (if needed) match zips")
    p_pull.add_argument("--force", action="store_true")

    p_build = sub.add_parser("build", help="Parse matches to Parquet and compute standings")
    p_build.add_argument("--no-metrics", action="store_true")
    p_build.add_argument("--workers", type=int, default=None)

    sub.add_parser("rebuild-metrics", help="Recompute T20 metrics from the warehouse")
    sub.add_parser("metrics", help="Alias of rebuild-metrics")

    p_serve = sub.add_parser("serve", help="Start the local UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)

    if args.cmd == "pull":
        from cricwarehouse.app.pull import pull

        pull(force=args.force)
        return 0
    if args.cmd == "build":
        from cricwarehouse.app.build import build

        build(workers=args.workers, with_metrics=not args.no_metrics)
        return 0
    if args.cmd in {"rebuild-metrics", "metrics"}:
        from cricwarehouse.app import metrics

        metrics.rebuild_metrics()
        return 0
    if args.cmd == "serve":
        from cricwarehouse.app.serve import serve

        serve(host=args.host, port=args.port)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
