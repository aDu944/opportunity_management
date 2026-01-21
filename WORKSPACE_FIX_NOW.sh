#!/bin/bash

# Quick workspace fix script
# This will install the workspace properly in your site

echo "========================================="
echo "FIXING OPPORTUNITY MANAGEMENT WORKSPACE"
echo "========================================="
echo ""

# Get site name from user
read -p "Enter your site name (e.g., mysite.localhost): " SITE_NAME

if [ -z "$SITE_NAME" ]; then
    echo "Error: Site name required"
    exit 1
fi

echo ""
echo "Installing workspace for site: $SITE_NAME"
echo ""

# Navigate to bench (assuming standard location)
if [ -d ~/frappe-bench ]; then
    cd ~/frappe-bench
elif [ -d ~/bench ]; then
    cd ~/bench
else
    echo "Enter your bench directory path:"
    read BENCH_DIR
    cd "$BENCH_DIR"
fi

echo "Current directory: $(pwd)"
echo ""

# Run the installation
echo "Running workspace installation..."
bench --site "$SITE_NAME" console <<EOF
from opportunity_management.install_workspace import install_workspace
install_workspace()
exit()
EOF

# Clear cache
echo ""
echo "Clearing cache..."
bench --site "$SITE_NAME" clear-cache

# Restart
echo ""
echo "Restarting bench..."
bench restart

echo ""
echo "========================================="
echo "✅ WORKSPACE INSTALLATION COMPLETE!"
echo "========================================="
echo ""
echo "Now do these steps:"
echo "1. Open your browser"
echo "2. Press Ctrl+Shift+R (hard refresh)"
echo "3. Look for 'Opportunity Management' in sidebar"
echo "4. It should now have a briefcase icon"
echo "5. Click it to see all links"
echo ""
