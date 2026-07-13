# ComfyUI-Wudd-V3 Maintenance Notes

This file is a short maintainer reference for the current V3 package. It is not loaded by ComfyUI at runtime.

## Runtime Entry Points

- `__init__.py` exposes `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS`, `WEB_DIRECTORY`, and `comfy_entrypoint`.
- ComfyUI currently registers this package through `NODE_CLASS_MAPPINGS`; the node classes themselves use `comfy_api.latest.IO.ComfyNode` V3 schemas.
- `WEB_DIRECTORY = "./web"` loads the JavaScript extensions in `web/js`.

## Structure

- `nodes/` contains V3 schema wrappers and ComfyUI-facing node classes.
- `core/` contains the backend implementations used by the V3 wrappers.
- `locales/zh/nodeDefs.json` contains current `WuddV3...` Chinese node labels, descriptions, and tooltips.
- `web/js/dynamic_ports.js` adjusts visible output/input counts for selected dynamic-port nodes.
- `web/js/group_switch.js` adds canvas-group controls for `WuddV3GroupSwitch`.
- `web/js/wireless.js` registers the frontend-only wireless virtual nodes.

## Registered Python Nodes

All Python nodes are registered under `Wudd Nodes V3` or a subcategory:

- `WuddV3MultiSaveImage`
- `WuddV3SaveVideo`
- `WuddV3FastForwardVideo`
- `WuddV3ConcatVideos`
- `WuddV3TextSplitter`
- `WuddV3MultiTextSplitter`
- `WuddV3PromptListFromText`
- `WuddV3SaveText`
- `WuddV3DropAlpha`
- `WuddV3ImageExpand`
- `WuddV3EdgePad`
- `WuddV3ImageListImporter`
- `WuddV3ImageStitch`
- `WuddV3PathJoiner`
- `WuddV3VideoAudioExtractor`
- `WuddV3ReplaceVideoAudio`
- `WuddV3OpenRouterGPTText`
- `WuddV3OpenRouterClaudeText`
- `WuddV3OpenRouterGeminiText`
- `WuddV3OpenRouterGPTImage`
- `WuddV3OpenRouterGeminiImage`
- `WuddV3GroupSwitch`
- `WuddV3ChatGPTBrowser`

The wireless input/output nodes are frontend-only LiteGraph nodes:

- `WuddV3WirelessInput`
- `WuddV3WirelessOutput`

## Help And Tooltips

Node help is centralized in `nodes/_base.py`:

- `WUDD_V3_HELP` stores English schema descriptions and tooltips.
- `_with_help(schema)` applies the help data to node descriptions, inputs, nested dynamic inputs, and outputs.
- Each V3 node returns `_with_help(IO.Schema(...))`.

When adding or renaming a node input/output:

1. Update the V3 schema in the matching `nodes/<category>/wudd_v3_*.py` module.
2. Update `WUDD_V3_HELP` in `nodes/_base.py`.
3. Update `locales/zh/nodeDefs.json`.
4. Run the schema and functional checks.

## Dynamic Inputs

The package intentionally uses ComfyUI V3 dynamic frontend extensions:

- `COMFY_AUTOGROW_V3` for dynamic image/video slot groups.
- `COMFY_DYNAMICCOMBO_V3` for option-specific nested inputs.

These are valid for current ComfyUI V3 schemas, but external validators that only know the published primitive NodeDef branches may report them as extension types.

## Validation

Use the portable Python bundled with ComfyUI when available:

```powershell
C:\Users\V\Documents\ComfyUI\python_embeded\python.exe scripts\functional_check_nodes.py
```

Expected local result:

- Local non-API nodes should pass.
- OpenRouter live API nodes are intentionally skipped by the functional check.
- `WuddV3ChatGPTBrowser` reports `ENV_FAIL` unless a browser CDP endpoint is available at `http://127.0.0.1:9222`.
