#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


def validate_structure(repository, policy_file):
    with open(policy_file, "r", encoding="utf-8") as file:
        policy = yaml.safe_load(file)

    errors = []

    for relative_path, approved_names in policy.items():
        component_path = repository / relative_path
        approved = set(approved_names)

        if not component_path.is_dir():
            errors.append(f"Missing protected directory: {relative_path}")
            continue

        actual = {
            entry.name
            for entry in component_path.iterdir()
            if entry.is_dir()
        }

        for name in sorted(actual - approved):
            errors.append(
                f"UNAUTHORISED component: {relative_path}/{name}"
            )

        for name in sorted(approved - actual):
            errors.append(
                f"MISSING approved component: {relative_path}/{name}"
            )

    return errors

def validate_component_changes(repository, policy_file, base_ref="origin/main"):
    """
    Reject changes to files within policy-controlled component directories.
    Compare the working tree against the trusted Git baseline.
    """

    with open(policy_file, "r", encoding="utf-8") as file:
        policy = yaml.safe_load(file)

    protected_paths = tuple(
        path.rstrip("/") + "/" for path in policy.keys()
    )

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "diff",
            "--name-only",
            base_ref,
            "--",
            *protected_paths,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    errors = []

    for changed_file in result.stdout.splitlines():
        errors.append(
            f"PROTECTED component file changed: {changed_file}"
        )

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Validate OpenShift component directory structure"
    )

    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Path to the platform repository"
    )

    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "policies/repository-structure/approved-components.yaml",
        help="Path to the approved components policy"
    )

    args = parser.parse_args()

    if not args.repo.is_dir():
        print(f"ERROR: Repository not found: {args.repo}")
        sys.exit(2)

    try:
        errors = validate_structure(args.repo, args.policy)

        errors.extend(
            validate_component_changes(args.repo, args.policy)
    )
    except (
        OSError,
        yaml.YAMLError,
        ValueError,
        TypeError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"ERROR: Validation could not complete: {exc}")
        sys.exit(2)

    if errors:
        print("Governance validation: FAILED")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    print("Governance validation: PASSED")
    print("All protected component directories match the approved policy.")
    sys.exit(0)


if __name__ == "__main__":
    main()
