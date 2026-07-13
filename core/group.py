"""
Group control helper nodes.
"""

class WuddGroupSwitch:
    def switch_group(self, enabled, group_name="", off_mode="mute"):
        return (bool(enabled), group_name or "")
