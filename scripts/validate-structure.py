
#!/usr/bin/env python3

"""
OpenShift GitOps Component Governance Validator

Validates:
1. Approved component directory structure.
2. Unauthorised component directories.
3. Missing approved component directories.
4. Changes to protected component files against a Git baseline.

Exit codes:
    0 - Validation passed
    1 - Governance violation detected
    2 - Validation execution error
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


def load_policy(policy_file):
    """Load the approved component policy."""

    with open(policy_file, "r", encoding="utf-8") as file:
        policy = yaml.safe_load(file)

    if not isinstance(policy, dict):
        raise ValueError("Policy must contain a YAML mapping")

    for path, approved_names in policy.items():
        if not isinstance(path, str):
            raise ValueError("Policy directory paths must be strings")

        if not isinstance(approved_names, list):
            raise ValueError(
                f"Approved components for {path} must be a list"
            )

        if not all(isinstance(name, str) for name in approved_names):
            raise ValueError(
                f"Approved component names for {path} must be strings"
            )

    return policy


def validate_structure(repository, policy):
    """
    Validate directory structure against the approved policy.
    """

    errors = []

    for relative_path, approved_names in policy.items():

        component_path = repository / relative_path
        approved = set(approved_names)

        if not component_path.is_dir():
            errors.append(
                f"MISSING protected directory: {relative_path}"
            )
            continue

        actual = {
            entry.name
            for entry in component_path.iterdir()
            if entry.is_dir()
        }

        # Detect unauthorised directories
        for name in sorted(actual - approved):
            errors.append(
                f"UNAUTHORISED component: {relative_path}/{name}"
            )

        # Detect missing approved directories
        for name in sorted(approved - actual):
            errors.append(
                f"MISSING approved component: {relative_path}/{name}"
            )

    return errors



def validate_component_changes(repository, policy, base_ref):
    """
    Detect changes within protected component directories.

    Checks:
    - Committed modifications, additions and deletions.
    - Tracked changes in the working tree and index.
    - Untracked files not excluded by .gitignore.
    """

    protected_paths = [
        path.rstrip("/") + "/"
        for path in policy.keys()
    ]

    # Detect tracked changes against the Git baseline.
    diff_result = subprocess.run(
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

    # Detect untracked files within protected directories.
    untracked_result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            *protected_paths,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    errors = []

    for changed_file in sorted(set(diff_result.stdout.splitlines())):
        errors.append(
            f"PROTECTED component file changed: {changed_file}"
        )

    for untracked_file in sorted(
        set(untracked_result.stdout.splitlines())
    ):
        errors.append(
            f"UNTRACKED file in protected component: {untracked_file}"
        )

    return errors

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Validate OpenShift GitOps component governance"
        )
    )

    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Path to the OpenShift platform repository"
    )

    parser.add_argument(
        "--policy",
        type=Path,
        default=(
            Path(__file__).resolve().parent.parent
            / "policies/repository-structure/approved-components.yaml"
        ),
        help="Path to the approved components policy"
    )

    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Trusted Git baseline for component change detection"
    )

    args = parser.parse_args()

    repository = args.repo.resolve()
    policy_file = args.policy.resolve()

    if not repository.is_dir():
        print(f"ERROR: Repository not found: {repository}")
        sys.exit(2)

    try:

        # Load governance policy
        policy = load_policy(policy_file)

        # Validate directory structure
        errors = validate_structure(
            repository,
            policy
        )

        # Validate protected component changes
        errors.extend(
            validate_component_changes(
                repository,
                policy,
                args.base_ref
            )
        )

    except (
        OSError,
        yaml.YAMLError,
        ValueError,
        TypeError,
        subprocess.CalledProcessError,
    ) as exc:

        print(
            f"ERROR: Governance validation could not complete: {exc}"
        )
        sys.exit(2)

    if errors:

        print("Governance validation: FAILED")

        for error in errors:
            print(f"  - {error}")

        sys.exit(1)

    print("Governance validation: PASSED")
    print(
        "All protected component directories "
        "match the approved governance policy."
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
