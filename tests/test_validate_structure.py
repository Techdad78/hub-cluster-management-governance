
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


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
        """Create an isolated temporary platform repository."""

        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

        # Legacy policy format, retained for regression testing.
        self.policy = {
            "gitops/components/operators": [
                "acm",
                "acs",
            ],
            "gitops/components/storage": [
                "hitachi",
            ],
        }

        # New policy format with recursive component protection.
        self.expanded_policy = {
            "protected_paths": [
                "gitops/components",
            ],
            "approved_directories": {
                "gitops/components": [
                    "common",
                    "management",
                    "operators",
                    "security",
                    "storage",
                    "virtualization",
                    "workload",
                ],
            },
        }

        for path, components in self.policy.items():
            for component in components:
                (self.repo / path / component).mkdir(
                    parents=True,
                    exist_ok=True,
                )

        for path, components in (
            self.expanded_policy["approved_directories"].items()
        ):
            for component in components:
                (self.repo / path / component).mkdir(
                    parents=True,
                    exist_ok=True,
                )

    def tearDown(self):
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
        return (
            self.repo
            / "gitops/components/operators/acm"
            / name
        )

    def assert_protected_change(self, errors, filename):
        self.assertTrue(
            any(
                "PROTECTED component file changed" in error
                and filename in error
                for error in errors
            ),
            f"Expected protected file violation, got: {errors}"
        )

    # --------------------------------------------------
    # Original directory structure tests
    # --------------------------------------------------

    def test_approved_structure_passes(self):
        errors = validator.validate_structure(
            self.repo, self.policy
        )
        self.assertEqual(errors, [])

    def test_unauthorised_component_fails(self):
        (
            self.repo
            / "gitops/components/operators/unknown-operator"
        ).mkdir()

        errors = validator.validate_structure(
            self.repo, self.policy
        )

        self.assertTrue(
            any("UNAUTHORISED component" in e for e in errors)
        )

    def test_missing_approved_component_fails(self):
        (
            self.repo
            / "gitops/components/operators/acm"
        ).rmdir()

        errors = validator.validate_structure(
            self.repo, self.policy
        )

        self.assertTrue(
            any("MISSING approved component" in e for e in errors)
        )

    # --------------------------------------------------
    # Original Git-based change detection tests
    # --------------------------------------------------

    def test_modified_component_file_fails(self):
        self.init_git_repository()

        component = self.component_file()
        component.write_text("kind: ConfigMap\n")

        baseline = self.commit_baseline()

        component.write_text("kind: Secret\n")

        errors = validator.validate_component_changes(
            self.repo, self.policy, baseline
        )

        self.assert_protected_change(
            errors, "acm/component.yaml"
        )

    def test_committed_file_addition_fails(self):
        self.init_git_repository()
        baseline = self.commit_baseline()

        component = self.component_file("new-component.yaml")
        component.write_text("kind: ConfigMap\n")

        self.run_git("add", ".")
        self.run_git(
            "commit", "-q", "-m", "Add component"
        )

        errors = validator.validate_component_changes(
            self.repo, self.policy, baseline
        )

        self.assert_protected_change(
            errors, "acm/new-component.yaml"
        )

    def test_committed_file_deletion_fails(self):
        self.init_git_repository()

        component = self.component_file()
        component.write_text("kind: ConfigMap\n")

        baseline = self.commit_baseline()

        self.run_git(
            "rm",
            "gitops/components/operators/acm/component.yaml"
        )
        self.run_git(
            "commit", "-q", "-m", "Delete component"
        )

        errors = validator.validate_component_changes(
            self.repo, self.policy, baseline
        )

        self.assert_protected_change(
            errors, "acm/component.yaml"
        )

    def test_untracked_file_fails(self):
        self.init_git_repository()
        baseline = self.commit_baseline()

        component = self.component_file("untracked.yaml")
        component.write_text("kind: ConfigMap\n")

        errors = validator.validate_component_changes(
            self.repo, self.policy, baseline
        )

        self.assertTrue(
            any(
                "UNTRACKED file in protected component" in e
                and "acm/untracked.yaml" in e
                for e in errors
            )
        )

    # --------------------------------------------------
    # Expanded recursive protection tests
    # --------------------------------------------------

    def test_security_component_modification_fails(self):
        """T08: Changes under security must be rejected."""

        self.init_git_repository()

        component = (
            self.repo
            / "gitops/components/security/security-config.yaml"
        )
        component.write_text("kind: ConfigMap\n")

        baseline = self.commit_baseline()

        component.write_text("kind: Secret\n")

        errors = validator.validate_component_changes(
            self.repo, self.expanded_policy, baseline
        )

        self.assert_protected_change(
            errors, "security/security-config.yaml"
        )

    def test_common_component_addition_fails(self):
        """T09: New files in nested common paths must fail."""

        self.init_git_repository()
        baseline = self.commit_baseline()

        component_dir = (
            self.repo
            / "gitops/components/common/authentication"
        )
        component_dir.mkdir(parents=True, exist_ok=True)

        component = component_dir / "oauth.yaml"
        component.write_text("kind: OAuth\n")

        self.run_git("add", ".")
        self.run_git(
            "commit", "-q", "-m", "Add OAuth configuration"
        )

        errors = validator.validate_component_changes(
            self.repo, self.expanded_policy, baseline
        )

        self.assert_protected_change(
            errors, "common/authentication/oauth.yaml"
        )

    def test_changes_outside_components_pass(self):
        """T10: Unprotected paths must remain editable."""

        self.init_git_repository()

        config_dir = self.repo / "gitops/clusters/site-a"
        config_dir.mkdir(parents=True, exist_ok=True)

        config = config_dir / "configuration.yaml"
        config.write_text("environment: dev\n")

        baseline = self.commit_baseline()

        config.write_text("environment: prod\n")

        errors = validator.validate_component_changes(
            self.repo, self.expanded_policy, baseline
        )

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
