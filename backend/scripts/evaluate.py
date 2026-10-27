"""Validate the maintained evaluation data or run the opt-in full Phase 4 suite."""

import argparse
from evaluation.suite import load_cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    data = load_cases()
    print(f'Evaluation dataset: {len(data["cases"])} valid cases.', flush=True)
    if not args.validate_only:
        from scripts.verify_phase4 import run
        run()


if __name__ == '__main__': main()
