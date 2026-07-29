"""Fixture-only benchmark placeholder.

The first benchmark phase will add repeated queue-inclusive measurements. This script
intentionally refuses any live-provider option.
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="Reserved and intentionally unavailable before provider approval.",
    )
    args = parser.parse_args()
    if args.live:
        raise SystemExit("Live probes are disabled until Phase 0 provider approval.")
    print("Fixture benchmark boundary is ready; no network calls were made.")


if __name__ == "__main__":
    main()
