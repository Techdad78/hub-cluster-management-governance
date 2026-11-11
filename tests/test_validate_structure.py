
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


# Load the governance validator.
SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts/validate-structure.py"
)

spec = importlib.util.spec_from_file_location(
    "validate_structure", SCRIPT
)

validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class TestComponentStructure(unittest.TestCase):

    def setUp(self):
        """Create an isolated temporary component repository."""

        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

        self.policy = {
            "gitops/components/operators": [
                "acm",
                "acs",
            ],
            "gitops/components/storage": [
                "hitachi",
            ],
        }

        for path, components in self.policy.items():
            for component in components:
                (self.repo / path / component).mkdir(
                    parents=True,
                    exist_ok=True,
                )

    def tearDown(self):
        """Remove the temporary repository after each test."""

        self.temp_dir.cleanup()

    def run_git(self, *args):
        """Run Git in the temporary repository."""

        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def init_git_repository(self):
        """Initialise Git and configure a test identity."""

        self.run_git("init", "-q")
        self.run_git(
            "config", "user.email", "ci-test@example.com"
        )
        self.run_git(
            "config", "user.name", "CI Test"
        )

    def commit_baseline(self):
        """Commit current files and return the baseline SHA."""

        self.run_git("add", ".")

        self.run_git(
            "commit", "-q", "--allow-empty",
            "-m", "Approved baseline"
        )

        return self.run_git(
            "rev-parse", "HEAD"
        ).stdout.strip()

    def component_file(self, name="component.yaml"):
        """Return a file path inside the protected ACM component."""

        return (
            self.repo
            / "gitops/components/operators/acm"
            / name
        )

    def assert_protected_change(self, errors, filename):
        """Confirm the expected protected file was reported."""

        self.assertTrue(
            any(
                "PROTECTED component file changed" in error
                and filename in error
                for error in errors
            ),
            f"Expected protected file violation, got: {errors}"
        )

    # --------------------------------------------------
    # Directory structure tests
    # --------------------------------------------------

    def test_approved_structure_passes(self):
        """Approved component directories should pass."""

        errors = validator.validate_structure(
            self.repo,
            self.policy,
        )

        self.assertEqual(errors, [])

    def test_unauthorised_component_fails(self):
        """An unknown component directory should be rejected."""

        (
            self.repo
            / "gitops/components/operators/unknown-operator"
        ).mkdir()

        errors = validator.validate_structure(
            self.repo,
            self.policy,
        )

        self.assertTrue(
            any(
                "UNAUTHORISED component" in error
                for error in errors
            )
        )

    def test_missing_approved_component_fails(self):
        """A missing approved component should be rejected."""

        (
            self.repo
            / "gitops/components/operators/acm"
        ).rmdir()

        errors = validator.validate_structure(
            self.repo,
            self.policy,
        )

        self.assertTrue(
            any(
                "MISSING approved component" in error
                for error in errors
            )
        )

    # --------------------------------------------------
    # Git-based component change tests
    # --------------------------------------------------

    def test_modified_component_file_fails(self):
        """Modification of a protected file should be rejected."""

        self.init_git_repository()

        component = self.component_file()
        component.write_text(
            "kind: ConfigMap\n",
            encoding="utf-8",
        )

        baseline = self.commit_baseline()

        component.write_text(
            "kind: Secret\n",
            encoding="utf-8",
        )

        errors = validator.validate_component_changes(
            self.repo,
            self.policy,
            baseline,
        )

        self.assert_protected_change(
            errors, "acm/component.yaml"
        )

    def test_committed_file_addition_fails(self):
        """A committed new protected file should be rejected."""

        self.init_git_repository()
        baseline = self.commit_baseline()

        component = self.component_file("new-component.yaml")
        component.write_text(
            "kind: ConfigMap\n",
            encoding="utf-8",
        )

        self.run_git("add", ".")
        self.run_git(
            "commit", "-q", "-m", "Add component"
        )

        errors = validator.validate_component_changes(
            self.repo,
            self.policy,
            baseline,
        )

        self.assert_protected_change(
            errors, "acm/new-component.yaml"
        )

    def test_committed_file_deletion_fails(self):
        """Deletion of a protected file should be rejected."""

        self.init_git_repository()

        component = self.component_file()
        component.write_text(
            "kind: ConfigMap\n",
            encoding="utf-8",
        )

        baseline = self.commit_baseline()

        self.run_git(
            "rm",
            "gitops/components/operators/acm/component.yaml"
        )
        self.run_git(
            "commit", "-q", "-m", "Delete component"
        )

        errors = validator.validate_component_changes(
            self.repo,
            self.policy,
            baseline,
        )

        self.assert_protected_change(
            errors, "acm/component.yaml"
        )

    def test_untracked_file_fails(self):
        """An untracked file in a protected path should be rejected."""

        self.init_git_repository()
        baseline = self.commit_baseline()

        component = self.component_file("untracked.yaml")
        component.write_text(
            "kind: ConfigMap\n",
            encoding="utf-8",
        )

        errors = validator.validate_component_changes(
            self.repo,
            self.policy,
            baseline,
        )

        self.assertTrue(
            any(
                "UNTRACKED file in protected component" in error
                and "acm/untracked.yaml" in error
                for error in errors
            ),
            f"Expected untracked file violation, got: {errors}"
        )


if __name__ == "__main__":
    unittest.main()
