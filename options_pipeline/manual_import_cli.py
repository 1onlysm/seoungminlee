"""Command-line wrapper for local, offline options-file import."""
import argparse
import json
import sys

from .manual_import import ImportError, import_file


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import a user-supplied options CSV/JSON file offline")
    parser.add_argument("--input", required=True, help="Local .csv or .json file")
    parser.add_argument("--output", default="navi-options-imports", help="Local append-only snapshot directory")
    args = parser.parse_args(argv)
    try:
        result = import_file(args.input, args.output)
    except (ImportError, OSError) as exc:
        print(json.dumps({"status": "IMPORT_REJECTED", "error": f"{type(exc).__name__}:{exc}", "network_requests": 0}), file=sys.stderr)
        return 1
    print(json.dumps({"status": result["research_usability"], "evidence_kind": "USER_SUPPLIED_FILE_NOT_INDEPENDENTLY_VERIFIED",
                      "snapshot": result["snapshot_path"], "symbol": result["symbol"], "records": result["record_count"],
                      "structural_quality": result["structural_quality"], "freshness": result["freshness"],
                      "analytics": result["analytics"], "network_requests": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
