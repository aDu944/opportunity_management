#!/bin/bash

# Script to merge busy-turing branch to main
# This script handles the worktree scenario properly

set -e  # Exit on error

echo "========================================="
echo "Merging busy-turing branch to main"
echo "========================================="
echo ""

# Step 1: Verify we're in the worktree
CURRENT_DIR=$(pwd)
echo "✓ Current directory: $CURRENT_DIR"
echo ""

# Step 2: Check if there are uncommitted changes
echo "Checking for uncommitted changes in worktree..."
if [[ -n $(git status -s) ]]; then
    echo "⚠️  Warning: You have uncommitted changes in the worktree"
    git status -s
    echo ""
    read -p "Do you want to commit these changes first? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git add -A
        read -p "Enter commit message: " COMMIT_MSG
        git commit -m "$COMMIT_MSG"
        echo "✓ Changes committed"
    else
        echo "⚠️  Continuing with uncommitted changes..."
    fi
fi
echo ""

# Step 3: Navigate to main repository
MAIN_REPO="/Users/adu94/opportunity_management"
echo "Navigating to main repository: $MAIN_REPO"
cd "$MAIN_REPO"
echo "✓ Now in: $(pwd)"
echo ""

# Step 4: Checkout main branch
echo "Checking out main branch..."
git checkout main
echo "✓ On main branch"
echo ""

# Step 5: Show what will be merged
echo "Commits that will be merged from busy-turing:"
echo "---"
git log --oneline main..busy-turing
echo "---"
echo ""

# Step 6: Ask for confirmation
read -p "Proceed with merge? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Merge cancelled"
    exit 1
fi
echo ""

# Step 7: Merge the branch
echo "Merging busy-turing into main..."
if git merge busy-turing --no-ff -m "Merge branch 'busy-turing' - Add calendar view, team assignment, and auto-close features"; then
    echo "✓ Merge successful!"
else
    echo "❌ Merge failed - please resolve conflicts manually"
    exit 1
fi
echo ""

# Step 8: Show the result
echo "Latest commits on main:"
git log --oneline -5
echo ""

# Step 9: Ask about pushing to remote
read -p "Do you want to push to remote? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Pushing to origin/main..."
    if git push origin main; then
        echo "✓ Pushed to remote successfully"
    else
        echo "⚠️  Push failed - you may need to pull first or resolve conflicts"
    fi
else
    echo "ℹ️  Skipped push to remote. Run 'git push origin main' manually when ready."
fi
echo ""

# Step 10: Ask about cleaning up the worktree
echo "========================================="
echo "Cleanup Options"
echo "========================================="
echo ""
read -p "Do you want to delete the busy-turing branch? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git branch -d busy-turing
    echo "✓ Branch busy-turing deleted"
else
    echo "ℹ️  Branch busy-turing kept"
fi
echo ""

read -p "Do you want to remove the worktree directory? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git worktree remove "$CURRENT_DIR"
    echo "✓ Worktree removed: $CURRENT_DIR"
    echo "⚠️  Note: You're still in this directory, which will be deleted"
    echo "   Please navigate elsewhere (e.g., cd ~)"
else
    echo "ℹ️  Worktree directory kept: $CURRENT_DIR"
fi
echo ""

echo "========================================="
echo "✅ MERGE COMPLETE!"
echo "========================================="
echo ""
echo "Summary:"
echo "- busy-turing branch has been merged to main"
echo "- Main repository: $MAIN_REPO"
echo ""
echo "Next steps:"
echo "1. Navigate to your main repository: cd $MAIN_REPO"
echo "2. Deploy the changes to your Frappe site"
echo "3. Run: bench --site [your-site] migrate"
echo ""
