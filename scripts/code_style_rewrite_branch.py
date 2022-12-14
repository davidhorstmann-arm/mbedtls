#!/usr/bin/env python3
"""Rewrite a branch on top of a code style change commit so that all
new commits on the branch look as if they were created after the
code style change.
"""
# Copyright The Mbed TLS Contributors
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import subprocess
import sys
from typing import List

import code_style

def working_directory_clean() -> bool:
    """
    Check if the working directory is clean (i.e. no changes to tracked
    files staged or unstaged).
    """
    # Check for unstaged files
    result = subprocess.run(["git", "diff", "--exit-code"], \
            stdout=subprocess.PIPE, check=False)
    if result.returncode != 0:
        return False
    # Check for staged files
    result = subprocess.run(["git", "diff", "--cached", "--exit-code"], \
            stdout=subprocess.PIPE, check=False)
    if result.returncode != 0:
        return False
    return True

def delete_branch(branch_name) -> bool:
    """
    Delete the given branch.
    """
    # Go to detached HEAD state in case we are deleting the checked-out branch
    result = subprocess.run(["git", "checkout", "-d"], check=False)
    if result.returncode != 0:
        print("Error detaching HEAD.", file=sys.stderr)
        return False
    result = subprocess.run(["git", "branch", "-D", branch_name], check=False)
    if result.returncode != 0:
        print("Error deleting branch '" + branch_name + "'.", file=sys.stderr)
        return False
    return True

def rebase_on(branch: str, commit: str, new_branch: str) -> bool:
    """
    Make a new branch with the given name that consists of the given branch
    rebased on the given commit.
    """
    # Create a new branch from the existing branch
    result = subprocess.run(["git", "checkout", branch], check=False)
    if result.returncode != 0:
        print("Error checking out branch '"+branch+"'.", file=sys.stderr)
        return False
    result = subprocess.run(["git", "checkout", "-b", new_branch], check=False)
    if result.returncode != 0:
        print("Error creating rebase destination branch '"+new_branch+"'.", \
                file=sys.stderr)
        return False

    # Rebase the branch atop the given commit
    result = subprocess.run(["git", "rebase", commit], check=False)
    if result.returncode != 0:
        print("Error rebasing branch '"+branch+"' on commit '"+commit+"'.", \
                file=sys.stderr)
        delete_branch(new_branch)
        return False

    return True

def restyle_commit_onto_current(commit_hash: str) -> bool:
    """
    Re-style the given commit and add the result as a new commit on the given
    branch.
    """
    # Get a list of changed files in the commit
    result = subprocess.run(["git", "diff", "--name-only", commit_hash, \
            commit_hash + "~"], stdout=subprocess.PIPE, check=False)
    if result.returncode != 0:
        print("Error getting changed files for commit " + commit_hash + \
                ".", file=sys.stderr)
        return False
    changed_files = str(result.stdout, "ascii").strip().split()

    # Checkout changed files to their state in the old commit
    result = subprocess.run(["git", "checkout", commit_hash, "--"] + \
            changed_files, check=False)
    if result.returncode != 0:
        print("Error checking out changed files: " + ", ".join(changed_files) + \
                " to commit " + commit_hash + ".", file=sys.stderr)
        return False

    # Restyle the changed files to the new style
    if code_style.fix_style(changed_files) != 0:
        return False

    # Add the changed files
    result = subprocess.run(["git", "add"] + changed_files, check=False)
    if result.returncode != 0:
        print("Error adding changed files: " + ", ".join(changed_files) + \
                ".", file=sys.stderr)
        return False

    # Commit the newly added files
    result = subprocess.run(["git", "commit", "--reuse-message=" + \
            commit_hash], check=False)
    if result.returncode != 0:
        print("Error making restyled commit.", file=sys.stderr)
        return False

    return True

def list_revisions(revision_or_range: str) -> List[str]:
    """
    Return the list of commits in revision_or_range.

    If revision_or_range is a single revision, return it in a one-element
    list. Otherwise return the list of commits in that range.

    Return the list in order from oldest to newest.
    """
    result = subprocess.run(["git", "rev-list", "--no-walk", \
            revision_or_range], stdout=subprocess.PIPE, check=False)
    if result.returncode != 0:
        print("Error getting revision list for '"+revision_or_range+"'.", \
                file=sys.stderr)
        return []

    return list(reversed(str(result.stdout, "ascii").split()))

def rewrite_branch_code_style(existing_branch: str, new_branch: str, \
        codestyle_change_commit: str) -> bool:
    """
    Rewrite the given existing branch onto the given new branch on top of the
    given commit that changes the code style.
    """
    # Create the new branch to rewrite onto at the code style change commit
    result = subprocess.run(["git", "checkout", codestyle_change_commit], \
            check=False)
    if result.returncode != 0:
        print("Error checking out code style commit '" + \
                codestyle_change_commit + "'.", file=sys.stderr)
        return False
    result = subprocess.run(["git", "checkout", "-b", new_branch], check=False)
    if result.returncode != 0:
        print("Error creating destination branch '"+new_branch+"'.", \
                file=sys.stderr)
        return False

    # List all the commits between the commit before the codestyle change
    # (where the branch diverged) and the tip of the branch.
    for rev in list_revisions(codestyle_change_commit+"~.."+existing_branch):
        if not restyle_commit_onto_current(rev):
            delete_branch(new_branch)
            return False

    return True

def main() -> int:
    """
    Main with command line arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('existing_branch', \
            help='branch to rewrite with code style changes')
    parser.add_argument('destination_branch', \
            help='name of new branch for rewritten history (must not be the' \
            'same as existing_branch)')
    parser.add_argument('code_style_commit', \
            help='the commit containing the code style changes')

    args = parser.parse_args()

    # Check that the working directory is clean
    if not working_directory_clean():
        print("Error: Working directory is not clean.", file=sys.stderr)
        return 1

    # First rebase the branch on the commit preceding the code style change
    rebased_existing_branch = "rebased-"+args.existing_branch
    if not rebase_on(args.existing_branch, args.code_style_commit+"~", \
            rebased_existing_branch):
        return 1

    # Then rewrite other commits to be code-styled
    if not rewrite_branch_code_style(rebased_existing_branch, \
            args.destination_branch, args.code_style_commit):
        delete_branch(rebased_existing_branch)
        return 1

    # Delete the temporary rebased branch
    if not delete_branch(rebased_existing_branch):
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(main())
