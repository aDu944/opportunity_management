"""
/outlook - share page for the Outlook add-in: a download button for the
stable manifest and the install steps. Sent to colleagues instead of the raw
manifest link (browsers show XML instead of downloading it). Guest-readable:
the manifest is public anyway and signing in happens inside Outlook.
"""

from opportunity_management.opportunity_management import outlook_addin_pure as pure

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False
    context.title = "ERPNext for Outlook"
    context.manifest_url = f"{pure.ASSET_ROOT}/{pure.STABLE_DIR}/manifest.xml"
    context.icon_url = f"{pure.ASSET_ROOT}/{pure.STABLE_DIR}/icon-80.png"
    return context
