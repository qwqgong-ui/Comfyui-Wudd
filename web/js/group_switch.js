import { app } from "../../../scripts/app.js";

const MODE_ALWAYS = 0;
const MODE_NEVER = 2;
const MODE_BYPASS = 4;
const GROUP_SWITCH_CLASS = "WuddV3GroupSwitch";
const AUTO_GROUP_NAMES = new Set(["auto", "current", "self"]);
const GROUP_STATES_PROPERTY = "group_states";
const MIN_NODE_WIDTH = 320;
const GROUP_WIDGET_RESERVED_WIDTH = 98;
const MIN_GROUP_WIDGET_LABEL_WIDTH = 120;
const FALLBACK_CHAR_WIDTH = 7;
const GROUP_COLOR_FALLBACK = "#777777";
const GROUP_COLOR_LABEL_PREFIX = "    ";
const GROUP_COLOR_LABEL_PADDING = 26;
const GROUP_COLOR_SWATCH_X = 22;
const GROUP_COLOR_SWATCH_SIZE = 10;
const GROUP_COLOR_SWATCH_RADIUS = 3;

function getNodeWidget(node, name) {
    return node.widgets?.find(w => w.name === name);
}

function getNodeWidgetValue(node, name, fallback = undefined) {
    const widget = getNodeWidget(node, name);
    if (widget && widget.value !== undefined) return widget.value;
    return node.properties?.[name] ?? fallback;
}

function setNodeWidgetValue(node, name, value, triggerCallback = false) {
    const widget = getNodeWidget(node, name);
    if (widget) {
        widget.value = value;
        if (triggerCallback && typeof widget.callback === "function") {
            widget.callback.call(widget, value);
        }
        return true;
    }

    node.properties ??= {};
    node.properties[name] = value;
    return false;
}

function toBoolean(value) {
    if (typeof value === "string") {
        const v = value.trim().toLowerCase();
        return !(v === "" || v === "false" || v === "0" || v === "no" || v === "off");
    }
    return value === true || value === 1;
}

function toBoundsArray(bounds) {
    if (!bounds) return null;
    if (Array.isArray(bounds) || ArrayBuffer.isView(bounds)) {
        if (bounds.length < 4) return null;
        return [
            Number(bounds[0]) || 0,
            Number(bounds[1]) || 0,
            Number(bounds[2]) || 0,
            Number(bounds[3]) || 0,
        ];
    }

    if (typeof bounds === "object") {
        const x = bounds.x ?? bounds.left;
        const y = bounds.y ?? bounds.top;
        const w = bounds.width ?? bounds.w;
        const h = bounds.height ?? bounds.h;
        if ([x, y, w, h].every(v => Number.isFinite(Number(v)))) {
            return [Number(x), Number(y), Number(w), Number(h)];
        }
    }
    return null;
}

function getNodeBounds(node) {
    try {
        return toBoundsArray(node.getBounding?.()) ||
               toBoundsArray(node.boundingRect) ||
               (node.pos && node.size ? [node.pos[0], node.pos[1], node.size[0], node.size[1]] : null);
    } catch (e) {
        return null;
    }
}

function getGroupBounds(group) {
    return toBoundsArray(group?._bounding) ||
           toBoundsArray(group?.bounding) ||
           (group?.pos && group?.size ? [group.pos[0], group.pos[1], group.size[0], group.size[1]] : null);
}

function boundsOverlap(a, b) {
    const lg = globalThis.LiteGraph;
    if (lg?.overlapBounding) {
        try { return lg.overlapBounding(a, b); } catch (e) {}
    }
    return !(a[0] > b[0] + b[2] ||
             a[1] > b[1] + b[3] ||
             a[0] + a[2] < b[0] ||
             a[1] + a[3] < b[1]);
}

function getGraphGroups() {
    return Array.from(app.graph?._groups || app.graph?.groups || []);
}

function getGroupTitle(group) {
    return String(group?.title || "(untitled group)");
}

function getGroupKey(group) {
    if (group?.id != null) return `id:${group.id}`;
    const bounds = getGroupBounds(group);
    if (bounds) return `bounds:${getGroupTitle(group)}:${bounds[0]}:${bounds[1]}`;
    return `title:${getGroupTitle(group)}`;
}

function clampColorChannel(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(255, Math.round(n)));
}

function normalizeCssColor(value) {
    if (Array.isArray(value) && value.length >= 3) {
        return `rgb(${clampColorChannel(value[0])}, ${clampColorChannel(value[1])}, ${clampColorChannel(value[2])})`;
    }

    if (value && typeof value === "object") {
        const r = value.r ?? value.red;
        const g = value.g ?? value.green;
        const b = value.b ?? value.blue;
        if ([r, g, b].every(v => Number.isFinite(Number(v)))) {
            return `rgb(${clampColorChannel(r)}, ${clampColorChannel(g)}, ${clampColorChannel(b)})`;
        }
    }

    const color = String(value || "").trim();
    if (!color || color.toLowerCase() === "transparent") return "";
    return color;
}

function getGroupColor(group) {
    const candidates = [
        group?.color,
        group?._color,
        group?.bgcolor,
        group?._bgcolor,
        group?.properties?.color,
        group?.properties?.bgcolor,
    ];

    for (const candidate of candidates) {
        const colorOption = globalThis.LGraphCanvas?.node_colors?.[candidate];
        const groupColor = normalizeCssColor(colorOption?.groupcolor || colorOption?.color || colorOption?.bgcolor);
        if (groupColor) return groupColor;

        const color = normalizeCssColor(candidate);
        if (color) return color;
    }
    return GROUP_COLOR_FALLBACK;
}

function fallbackTextWidth(text) {
    let units = 0;
    for (const char of Array.from(String(text || ""))) {
        units += char.charCodeAt(0) > 255 ? 2 : 1;
    }
    return units * FALLBACK_CHAR_WIDTH;
}

function measureTextWidth(text) {
    const ctx = app.canvas?.ctx;
    if (!ctx?.measureText) return fallbackTextWidth(text);

    const previousFont = ctx.font;
    try {
        ctx.font = "12px Arial";
        const width = ctx.measureText(String(text || "")).width;
        return Number.isFinite(width) ? width : fallbackTextWidth(text);
    } catch (e) {
        return fallbackTextWidth(text);
    } finally {
        ctx.font = previousFont;
    }
}

function truncateMiddleToWidth(text, maxWidth) {
    const value = String(text || "");
    if (measureTextWidth(value) <= maxWidth) return value;

    const chars = Array.from(value);
    const marker = "...";
    if (chars.length <= marker.length || maxWidth <= measureTextWidth(marker)) return marker;

    let best = marker;
    let low = 1;
    let high = chars.length - 1;

    while (low <= high) {
        const keep = Math.floor((low + high) / 2);
        const head = Math.ceil(keep * 0.62);
        const tail = keep - head;
        const candidate = `${chars.slice(0, head).join("")}${marker}${tail ? chars.slice(chars.length - tail).join("") : ""}`;

        if (measureTextWidth(candidate) <= maxWidth) {
            best = candidate;
            low = keep + 1;
        } else {
            high = keep - 1;
        }
    }

    return best;
}

function getGroupWidgetLabelWidth(node) {
    const width = Number(node?.size?.[0]) || MIN_NODE_WIDTH;
    return Math.max(MIN_GROUP_WIDGET_LABEL_WIDTH, width - GROUP_WIDGET_RESERVED_WIDTH);
}

function formatGroupWidgetName(group, node = null) {
    const title = getGroupTitle(group);
    const name = group?.id != null ? `Group ${group.id}: ${title}` : `Group: ${title}`;
    if (!node) return name;

    const labelWidth = Math.max(
        MIN_GROUP_WIDGET_LABEL_WIDTH,
        getGroupWidgetLabelWidth(node) - GROUP_COLOR_LABEL_PADDING,
    );
    return `${GROUP_COLOR_LABEL_PREFIX}${truncateMiddleToWidth(name, labelWidth)}`;
}

function getGroupSignature() {
    return getGraphGroups()
        .map(group => `${getGroupKey(group)}:${getGroupTitle(group)}:${getGroupColor(group)}`)
        .sort()
        .join("|");
}

function isGraphNode(item) {
    return item && typeof item === "object" && item.id != null && typeof item.type === "string";
}

function isGroupSwitchNode(node) {
    return node?.comfyClass === GROUP_SWITCH_CLASS ||
           node?.type === GROUP_SWITCH_CLASS ||
           node?.constructor?.nodeData?.name === GROUP_SWITCH_CLASS;
}

function getGroupNodes(group) {
    try { group?.recomputeInsideNodes?.(); } catch (e) {}

    if (group?._children?.[Symbol.iterator]) {
        const children = Array.from(group._children).filter(isGraphNode);
        if (children.length) return children;
    }

    const groupBounds = getGroupBounds(group);
    const graphNodes = group?.graph?._nodes || app.graph?._nodes || [];
    if (!groupBounds) return Array.from(group?._nodes || []).filter(isGraphNode);

    const nodes = [];
    for (const node of graphNodes) {
        const nodeBounds = getNodeBounds(node);
        if (nodeBounds && boundsOverlap(groupBounds, nodeBounds)) {
            nodes.push(node);
        }
    }

    if (group) group._nodes = nodes;
    return nodes;
}

function groupArea(group) {
    const bounds = getGroupBounds(group);
    return bounds ? Math.max(0, bounds[2]) * Math.max(0, bounds[3]) : Number.MAX_SAFE_INTEGER;
}

function findTargetGroup(node) {
    const groups = getGraphGroups();
    const configuredName = String(getNodeWidgetValue(node, "group_name", "") || "").trim();
    const normalized = configuredName.toLowerCase();

    if (!AUTO_GROUP_NAMES.has(normalized)) {
        return groups.find(g => g.title === configuredName) ||
               groups.find(g => String(g.title || "").toLowerCase() === normalized) ||
               null;
    }

    return groups
        .filter(group => getGroupNodes(group).includes(node))
        .sort((a, b) => groupArea(a) - groupArea(b))[0] || null;
}

function ensureGroupStates(node) {
    node.properties ??= {};
    const states = node.properties[GROUP_STATES_PROPERTY];
    if (states && typeof states === "object" && !Array.isArray(states)) return states;
    node.properties[GROUP_STATES_PROPERTY] = {};
    return node.properties[GROUP_STATES_PROPERTY];
}

function getOffMode(node) {
    return String(getNodeWidgetValue(node, "off_mode", "mute") || "mute").toLowerCase();
}

function getGroupState(node, group) {
    const states = ensureGroupStates(node);
    const key = getGroupKey(group);
    if (states[key] === true || states[key] === false) return states[key];

    const isActive = getGroupNodes(group).some(target => target.mode === MODE_ALWAYS || target.mode == null);
    states[key] = isActive;
    return isActive;
}

function setGroupState(node, group, enabled) {
    const states = ensureGroupStates(node);
    states[getGroupKey(group)] = !!enabled;
}

function modeForState(node, enabled) {
    return enabled ? MODE_ALWAYS : (getOffMode(node) === "bypass" ? MODE_BYPASS : MODE_NEVER);
}

function applyGroupMode(group, enabled, ownerNode) {
    const targetMode = modeForState(ownerNode, enabled);
    let changed = false;

    for (const target of getGroupNodes(group)) {
        if (target === ownerNode || isGroupSwitchNode(target)) continue;
        if (target.mode !== targetMode) {
            target.mode = targetMode;
            target.setDirtyCanvas?.(true, true);
            changed = true;
        }
    }

    if (changed) {
        app.graph?.setDirtyCanvas?.(true, true);
    }
    return changed;
}

function refreshNode(node) {
    if (node.setSize && node.computeSize) {
        try {
            const computed = node.computeSize();
            if (Array.isArray(computed) || ArrayBuffer.isView(computed)) {
                const currentWidth = Number(node.size?.[0]) || 0;
                const currentHeight = Number(node.size?.[1]) || 0;
                const width = Math.max(currentWidth, Number(computed[0]) || 0, MIN_NODE_WIDTH);
                const height = Math.max(currentHeight, Number(computed[1]) || 0);
                if (width !== currentWidth || height !== currentHeight) {
                    node.setSize([width, height]);
                }
            }
        } catch (e) {}
    }
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
}

function syncGroupWidgetLabels(node) {
    const groups = getGraphGroups();
    let changed = false;

    for (const group of groups) {
        const widget = node.widgets?.find(w => w.__wuddGroupSwitchDynamic && w.__wuddGroupKey === getGroupKey(group));
        if (!widget) continue;

        const name = formatGroupWidgetName(group, node);
        const color = getGroupColor(group);
        if (widget.name !== name) {
            widget.name = name;
            changed = true;
        }
        if (widget.__wuddGroupColor !== color) {
            widget.__wuddGroupColor = color;
            changed = true;
        }
        widget.__wuddGroupFullName = formatGroupWidgetName(group);
    }

    node.__wuddGroupSwitchLabelWidth = Math.round(Number(node.size?.[0]) || 0);
    if (changed) {
        node.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas?.(true, true);
    }
    return changed;
}

function syncGroupWidgets(node) {
    const groups = getGraphGroups().sort((a, b) => getGroupTitle(a).localeCompare(getGroupTitle(b)));
    const groupKeys = new Set(groups.map(getGroupKey));
    let changed = false;

    for (let i = (node.widgets?.length || 0) - 1; i >= 0; i--) {
        const widget = node.widgets[i];
        if (!widget?.__wuddGroupSwitchDynamic) continue;
        if (!groupKeys.has(widget.__wuddGroupKey)) {
            node.widgets.splice(i, 1);
            changed = true;
        }
    }

    for (const group of groups) {
        const key = getGroupKey(group);
        let widget = node.widgets?.find(w => w.__wuddGroupSwitchDynamic && w.__wuddGroupKey === key);
        const value = getGroupState(node, group);
        const name = formatGroupWidgetName(group, node);
        const color = getGroupColor(group);

        if (!widget) {
            widget = node.addWidget("toggle", name, value, () => {
                setGroupState(node, group, widget.value);
                applyGroupMode(group, widget.value, node);
            }, { on: "run", off: "off" });
            widget.serialize = false;
            widget.__wuddGroupSwitchDynamic = true;
            widget.__wuddGroupKey = key;
            widget.__wuddGroupFullName = formatGroupWidgetName(group);
            widget.__wuddGroupColor = color;
            changed = true;
        } else {
            if (widget.name !== name) {
                widget.name = name;
                changed = true;
            }
            widget.__wuddGroupFullName = formatGroupWidgetName(group);
            if (widget.__wuddGroupColor !== color) {
                widget.__wuddGroupColor = color;
                changed = true;
            }
            if (widget.value !== value) {
                widget.value = value;
                changed = true;
            }
        }
    }

    node.__wuddGroupSwitchSignature = getGroupSignature();
    if (changed) refreshNode(node);
    return groups.length;
}

function setAllGroupStates(node, enabled) {
    syncGroupWidgets(node);
    for (const group of getGraphGroups()) {
        setGroupState(node, group, enabled);
        const widget = node.widgets?.find(w => w.__wuddGroupSwitchDynamic && w.__wuddGroupKey === getGroupKey(group));
        if (widget) widget.value = enabled;
    }
    applyDynamicGroupSwitches(node);
    refreshNode(node);
}

function applySingleGroupSwitch(node) {
    const group = findTargetGroup(node);
    if (!group) return false;

    const enabled = toBoolean(getNodeWidgetValue(node, "enabled", true));
    setGroupState(node, group, enabled);
    return applyGroupMode(group, enabled, node);
}

function applyDynamicGroupSwitches(node) {
    const groupCount = syncGroupWidgets(node);
    if (!groupCount) return applySingleGroupSwitch(node);

    let changed = false;
    for (const group of getGraphGroups()) {
        changed = applyGroupMode(group, getGroupState(node, group), node) || changed;
    }
    return changed;
}

function applyGroupSwitchNode(node) {
    const configuredName = String(getNodeWidgetValue(node, "group_name", "") || "").trim();
    if (configuredName) {
        return applySingleGroupSwitch(node);
    }
    return applyDynamicGroupSwitches(node);
}

function applyAllGroupSwitchNodes() {
    for (const node of app.graph?._nodes || []) {
        if (isGroupSwitchNode(node)) {
            try { applyGroupSwitchNode(node); } catch (e) {
                console.error("[Wudd] Group Switch error:", e);
            }
        }
    }
}

function patchGroupSwitchQueuePrompt() {
    if (typeof app.queuePrompt !== "function" ||
        app.queuePrompt === app.__wuddV3GroupSwitchWrappedQueuePrompt) {
        return;
    }

    const originalQueuePrompt = app.queuePrompt;
    const wrappedQueuePrompt = async function () {
        applyAllGroupSwitchNodes();
        return await originalQueuePrompt.apply(this, arguments);
    };
    app.queuePrompt = wrappedQueuePrompt;
    app.__wuddV3GroupSwitchWrappedQueuePrompt = wrappedQueuePrompt;
}

function patchDrawNodeWidgetsTarget(target) {
    if (!target ||
        typeof target.drawNodeWidgets !== "function" ||
        target.__wuddV3GroupSwitchWrappedDrawNodeWidgets) {
        return false;
    }

    const originalDrawNodeWidgets = target.drawNodeWidgets;
    target.drawNodeWidgets = function (node, posY, ctx) {
        const result = originalDrawNodeWidgets.apply(this, arguments);
        if (isGroupSwitchNode(node)) {
            try { drawGroupColorSwatches(node, ctx); } catch (e) {}
        }
        return result;
    };
    target.__wuddV3GroupSwitchWrappedDrawNodeWidgets = true;
    return true;
}

function patchGroupSwitchWidgetDrawing() {
    const canvasClass = globalThis.LGraphCanvas || app.canvas?.constructor;
    const patchedPrototype = patchDrawNodeWidgetsTarget(canvasClass?.prototype);
    if (patchedPrototype) return true;
    return patchDrawNodeWidgetsTarget(app.canvas);
}

function wrapCoreWidget(node, widgetName) {
    const widget = getNodeWidget(node, widgetName);
    if (!widget || widget.__wuddGroupSwitchWrapped) return;

    const originalCallback = widget.callback;
    widget.callback = function () {
        const result = originalCallback?.apply(this, arguments);
        if (widgetName === "enabled") {
            const configuredName = String(getNodeWidgetValue(node, "group_name", "") || "").trim();
            if (configuredName) applySingleGroupSwitch(node);
            else setAllGroupStates(node, toBoolean(widget.value));
        } else {
            applyGroupSwitchNode(node);
        }
        return result;
    };
    widget.__wuddGroupSwitchWrapped = true;
}

function setupGroupSwitchNode(node) {
    patchGroupSwitchQueuePrompt();
    patchGroupSwitchWidgetDrawing();
    node.flags ??= {};
    node.flags.resizable = true;
    node.resizable = true;

    const widgetNames = ["enabled", "group_name", "off_mode"];
    const widgets = widgetNames.map(name => getNodeWidget(node, name)).filter(Boolean);
    if (!widgets.length && (node.__wuddGroupSwitchSetupAttempts ?? 0) < 5) {
        node.__wuddGroupSwitchSetupAttempts = (node.__wuddGroupSwitchSetupAttempts ?? 0) + 1;
        setTimeout(() => setupGroupSwitchNode(node), 50);
        return;
    }

    for (const widgetName of widgetNames) {
        wrapCoreWidget(node, widgetName);
    }

    syncGroupWidgets(node);
    node.__wuddGroupSwitchReady = true;
    setTimeout(() => applyGroupSwitchNode(node), 50);
}

function maybeRefreshGroupWidgets(node) {
    const signature = getGroupSignature();
    if (signature !== node.__wuddGroupSwitchSignature) {
        syncGroupWidgets(node);
        return;
    }

    const width = Math.round(Number(node.size?.[0]) || 0);
    if (width !== node.__wuddGroupSwitchLabelWidth) {
        syncGroupWidgetLabels(node);
    }
}

function roundedRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

function drawGroupColorSwatches(node, ctx) {
    if (!ctx || !node.widgets?.length) return;

    const widgetHeight = globalThis.LiteGraph?.NODE_WIDGET_HEIGHT || 20;
    for (const widget of node.widgets) {
        if (!widget?.__wuddGroupSwitchDynamic) continue;

        const y = Number(widget.last_y ?? widget.y);
        if (!Number.isFinite(y)) continue;

        const swatchY = y + Math.max(0, (widgetHeight - GROUP_COLOR_SWATCH_SIZE) / 2);
        ctx.save();
        try {
            ctx.fillStyle = widget.__wuddGroupColor || GROUP_COLOR_FALLBACK;
            roundedRect(ctx, GROUP_COLOR_SWATCH_X, swatchY, GROUP_COLOR_SWATCH_SIZE, GROUP_COLOR_SWATCH_SIZE, GROUP_COLOR_SWATCH_RADIUS);
            ctx.fill();

            ctx.strokeStyle = "rgba(255, 255, 255, 0.38)";
            ctx.lineWidth = 1;
            roundedRect(ctx, GROUP_COLOR_SWATCH_X + 0.5, swatchY + 0.5, GROUP_COLOR_SWATCH_SIZE - 1, GROUP_COLOR_SWATCH_SIZE - 1, GROUP_COLOR_SWATCH_RADIUS);
            ctx.stroke();
        } catch (e) {
        } finally {
            ctx.restore();
        }
    }
}

app.registerExtension({
    name: "WuddV3.GroupSwitch",
    setup() {
        patchGroupSwitchQueuePrompt();
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== GROUP_SWITCH_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            try { setupGroupSwitchNode(this); } catch (e) {
                console.error("[Wudd] Group Switch setup error:", e);
            }
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (config) {
            if (onConfigure) onConfigure.apply(this, arguments);
            try {
                setupGroupSwitchNode(this);
                setTimeout(() => applyGroupSwitchNode(this), 50);
            } catch (e) {}
        };

        const onDrawBackground = nodeType.prototype.onDrawBackground;
        nodeType.prototype.onDrawBackground = function () {
            if (onDrawBackground) onDrawBackground.apply(this, arguments);
            try { maybeRefreshGroupWidgets(this); } catch (e) {}
        };

        const getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
            if (getExtraMenuOptions) getExtraMenuOptions.apply(this, arguments);

            const groups = getGraphGroups().sort((a, b) => getGroupTitle(a).localeCompare(getGroupTitle(b)));
            options.push(null);
            options.push({
                content: "Wudd: Refresh group list",
                callback: () => syncGroupWidgets(this),
            });
            options.push({
                content: "Wudd: Enable all groups",
                callback: () => setAllGroupStates(this, true),
            });
            options.push({
                content: "Wudd: Disable all groups",
                callback: () => setAllGroupStates(this, false),
            });
            options.push({
                content: "Wudd: Clear single target",
                callback: () => {
                    setNodeWidgetValue(this, "group_name", "", true);
                    this.setDirtyCanvas?.(true, true);
                },
            });
            options.push({
                content: "Wudd: Target one group",
                disabled: groups.length === 0,
                submenu: {
                    options: [
                        {
                            content: "Use containing group",
                            callback: () => {
                                setNodeWidgetValue(this, "group_name", "self", true);
                                this.setDirtyCanvas?.(true, true);
                            },
                        },
                        ...groups.map(group => ({
                            content: getGroupTitle(group),
                            callback: () => {
                                setNodeWidgetValue(this, "group_name", group.title || "", true);
                                this.setDirtyCanvas?.(true, true);
                            },
                        })),
                    ],
                },
            });
            options.push({
                content: "Wudd: Apply now",
                callback: () => applyGroupSwitchNode(this),
            });
        };
    },
});
