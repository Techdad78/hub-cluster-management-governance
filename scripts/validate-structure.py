
#!/usr/bin/env python3

"""
OpenShift GitOps Repository Governance Validator

Validates:
    1. Approved directory structure.
    2. Missing approved directories.
    3. Unauthorised directories.
    4. File additions within protected paths.
    5. File modifications within protected paths.
    6. File deletions within protected paths.
    7. Untracked files within protected paths.

Policy:
    policies/repository-structure/approved-components.yaml

Exit codes:
    0 - Governance validation passed
    1 - Governance violation detected
    2 - Validation execution error
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


def validate_path(path):
    """
    Validate that a policy path is a safe relative path.

    Prevent absolute paths and traversal outside the repository.
    """

    if not isinstance(path, str) or not path:
        raise ValueError("Policy path must be a non-empty string")

    candidate = Path(path)

    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or "\\" in path
    ):
        raise ValueError(f"Unsafe policy path: {path}")

    if path in (".", "/"):
        raise ValueError(f"Invalid policy path: {path}")


def load_policy(policy_file):
    """
    Load the governance policy.

    Expected YAML structure:

    protected_paths:
      - gitops/components

    approved_directories:
      gitops/components:
        - common
        - operators
        - storage
    """

    with open(policy_file, "r", encoding="utf-8") as file:
        policy = yaml.safe_load(file)

    if not isinstance(policy, dict):
        raise ValueError(
            "Governance policy must contain a YAML mapping"
        )

    if "protected_paths" not in policy:
        raise ValueError(
            "Governance policy missing 'protected_paths'"
        )

    if "approved_directories" not in policy:
        raise ValueError(
            "Governance policy missing 'approved_directories'"
        )

    protected_paths = policy["protected_paths"]
    approved_directories = policy["approved_directories"]

    if not isinstance(protected_paths, list) or not protected_paths:
        raise ValueError(
            "'protected_paths' must be a non-empty list"
        )

    if not isinstance(approved_directories, dict):
        raise ValueError(
            "'approved_directories' must be a mapping"
        )

    # Validate protected paths.
    for path in protected_paths:
        validate_path(path)

    # Validate approved directory definitions.
    for directory, approved_names in approved_directories.items():

        validate_path(directory)

        if not isinstance(approved_names, list):
            raise ValueError(
                f"Approved directories for {directory} "
                "must be a list"
            )

        for name in approved_names:

            validate_path(name)

            if "/" in name:
                raise ValueError(
                    f"Approved component must be a single "
                    f"directory name: {name}"
                )

    return policy


def validate_structure(repository, policy):
    """
    Validate the directory hierarchy against approved directories.

    Checks:
        - Protected parent directory exists.
        - Approved subdirectories exist.
        - Unauthorised subdirectories do not exist.

    Supports the original policy dictionary format
    for backwards compatibility with existing unit tests.
    """

    errors = []

    approved_directories = policy.get(
        "approved_directories",
        policy
    )

    for relative_path, approved_names in approved_directories.items():

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

        # Identify unauthorised component directories.
        for name in sorted(actual - approved):

            errors.append(
                f"UNAUTHORISED component: "
                f"{relative_path}/{name}"
            )

        # Identify missing approved component directories.
        for name in sorted(approved - actual):

            errors.append(
                f"MISSING approved component: "
                f"{relative_path}/{name}"
            )

    return errors


def validate_component_changes(repository, policy, base_ref):
    """
    Detect file changes within all protected paths.

    Uses Git to compare the repository against a trusted baseline.

    Detects:
        - Committed file additions.
        - Committed file modifications.
        - Committed file deletions.
        - Tracked working tree changes.
        - Untracked files not excluded by .gitignore.

    Supports the original policy dictionary format for
    backwards compatibility with existing unit tests.
    """

    protected_paths = policy.get(
        "protected_paths",
        list(policy.keys())
    )

    paths = [
        path.rstrip("/") + "/"
        for path in protected_paths
    ]

    # Detect all tracked changes compared with the baseline.
    diff_result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "diff",
            "--name-only",
            base_ref,
            "--",
            *paths,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Detect untracked files within protected paths.
    untracked_result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            *paths,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    errors = []

    changed_files = sorted(
        set(diff_result.stdout.splitlines())
    )

    untracked_files = sorted(
        set(untracked_result.stdout.splitlines())
    )

    # Report modified, added or deleted tracked files.
    for changed_file in changed_files:

        errors.append(
            f"PROTECTED component file changed: "
            f"{changed_file}"
        )

    # Report newly introduced untracked files.
    for untracked_file in untracked_files:

        errors.append(
            f"UNTRACKED file in protected component: "
            f"{untracked_file}"
        )

    return errors


def main():
    """
    Command-line entry point for governance validation.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Validate OpenShift GitOps repository governance"
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
        help="Path to the governance policy YAML file"
    )

    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Trusted Git baseline for change detection"
    )

    args = parser.parse_args()

    repository = args.repo.resolve()
    policy_file = args.policy.resolve()

    if not repository.is_dir():

        print(
            f"ERROR: Repository does not exist: {repository}"
        )

        sys.exit(2)

    try:

        # Load and validate governance policy.
        policy = load_policy(policy_file)

        # Validate approved directory hierarchy.
        structure_errors = validate_structure(
            repository,
            policy
        )

        # Validate protected file changes.
        change_errors = validate_component_changes(
            repository,
            policy,
            args.base_ref
        )

        errors = structure_errors + change_errors

    except (
        OSError,
        yaml.YAMLError,
        ValueError,
        TypeError,
        subprocess.CalledProcessError,
    ) as exc:

        print(
            f"ERROR: Governance validation "
            f"could not complete: {exc}"
        )

        sys.exit(2)

    if errors:

        print()
        print("Governance validation: FAILED")
        print()

        for error in errors:
            print(f"  - {error}")

        print()
        print(
            f"Total governance violations: {len(errors)}"
        )

        sys.exit(1)

    print()
    print("Governance validation: PASSED")
    print("All protected paths comply with governance policy.")
    print()

    sys.exit(0)


if __name__ == "__main__":
    main()
