from __future__ import annotations

from ._base import *


class WuddV3GroupSwitch(_BackendNode, IO.ComfyNode):
    BACKEND_CLS = WuddGroupSwitch

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="WuddV3GroupSwitch",
            display_name="Wudd V3 Group Switch",
            category=WUDD_V3_CATEGORY,
            inputs=[
                IO.Boolean.Input("enabled", default=True),
                IO.String.Input("group_name", default="", multiline=False),
                IO.Combo.Input("off_mode", options=["mute", "bypass"], default="mute"),
            ],
            outputs=[
                IO.Boolean.Output("enabled", display_name="enabled"),
                IO.String.Output("group_name", display_name="group_name"),
            ],
        )

    @classmethod
    async def execute(cls, enabled, group_name="", off_mode="mute") -> IO.NodeOutput:
        return await cls._run_backend(
            "switch_group",
            enabled=enabled,
            group_name=group_name,
            off_mode=off_mode,
        )


__all__ = ["WuddV3GroupSwitch"]
