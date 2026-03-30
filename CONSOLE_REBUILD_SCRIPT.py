# ERPNext Console Script to Force Rebuild Assets
# Copy and paste this entire script into your ERPNext System Console

import frappe
import os
import subprocess

def rebuild_assets():
    """Force rebuild of assets for opportunity_management app"""

    print("=" * 60)
    print("FORCING ASSET REBUILD FOR OPPORTUNITY_MANAGEMENT")
    print("=" * 60)

    # Step 1: Verify the JavaScript file has modern code
    print("\n[Step 1] Checking if source file has modern gradient code...")
    app_path = frappe.get_app_path("opportunity_management")
    js_file = os.path.join(app_path, "page", "team_opportunities", "team_opportunities.js")

    if os.path.exists(js_file):
        with open(js_file, 'r') as f:
            content = f.read()
            if 'linear-gradient' in content:
                print("✓ Source file HAS modern gradient code")
                gradient_count = content.count('linear-gradient')
                print(f"  Found {gradient_count} instances of 'linear-gradient'")
            else:
                print("✗ WARNING: Source file does NOT have gradient code!")
                print("  The deployment might not have pulled the latest code.")
                return
    else:
        print(f"✗ ERROR: File not found at {js_file}")
        return

    # Step 2: Clear all caches
    print("\n[Step 2] Clearing all caches...")
    frappe.clear_cache()
    print("✓ All caches cleared")

    # Step 3: Clear website cache
    print("\n[Step 3] Clearing website cache...")
    from frappe.website.utils import clear_cache as clear_website_cache
    clear_website_cache()
    print("✓ Website cache cleared")

    # Step 4: Build assets
    print("\n[Step 4] Building assets...")
    try:
        # Use frappe's build command
        from frappe.build import bundle

        print("  Building for app: opportunity_management")
        # Force rebuild by clearing build cache first
        build_cache_path = os.path.join(frappe.get_site_path(), ".build")
        if os.path.exists(build_cache_path):
            import shutil
            shutil.rmtree(build_cache_path)
            print("  Cleared build cache")

        # Build the assets
        bundle(
            "opportunity_management",
            no_compress=False,
            make_copy=False,
            verbose=True,
            skip_frappe=False
        )
        print("✓ Assets built successfully")

    except Exception as e:
        print(f"✗ Error building assets: {str(e)}")
        print("\nTrying alternative build method...")
        try:
            # Alternative: use command line
            subprocess.run(
                ["bench", "build", "--app", "opportunity_management", "--force"],
                check=True,
                cwd=frappe.get_site_path("..")
            )
            print("✓ Assets built via bench command")
        except Exception as e2:
            print(f"✗ Alternative build also failed: {str(e2)}")

    # Step 5: Verify built files
    print("\n[Step 5] Verifying built assets...")
    assets_path = os.path.join(
        frappe.get_site_path(),
        "assets",
        "opportunity_management",
        "page",
        "team_opportunities"
    )

    if os.path.exists(assets_path):
        files = os.listdir(assets_path)
        print(f"✓ Built assets directory exists")
        print(f"  Files: {', '.join(files)}")

        # Check if bundle file has the gradient code
        for filename in files:
            if filename.endswith('.bundle.js'):
                bundle_path = os.path.join(assets_path, filename)
                with open(bundle_path, 'r') as f:
                    bundle_content = f.read()
                    if 'linear-gradient' in bundle_content:
                        print(f"✓ Bundle file '{filename}' contains gradient code")
                    else:
                        print(f"✗ WARNING: Bundle file '{filename}' does NOT contain gradient code!")
    else:
        print(f"✗ WARNING: Assets directory not found at {assets_path}")

    print("\n" + "=" * 60)
    print("REBUILD COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Hard refresh your browser (Ctrl+Shift+R or Cmd+Shift+R)")
    print("2. Or open Team Opportunities in incognito/private window")
    print("3. You should now see modern gradient cards!")

# Run the rebuild
rebuild_assets()
