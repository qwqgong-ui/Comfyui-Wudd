import { app } from "../../../scripts/app.js";

const CATEGORY = "Wudd Nodes V3/Wireless";
const SENDER_NODE_TYPE = "WuddV3WirelessInput";
const RECEIVER_NODE_TYPE = "WuddV3WirelessOutput";
const DEFAULT_NAMESPACE = "main";
const DEFAULT_COUNT = 1;
const MAX_CHANNELS = 32;
const INPUT = 1;
const OUTPUT = 2;

function clampInt(value, min, max) {
    const n = Number.parseInt(value, 10);
    if (!Number.isFinite(n)) return min;
    return Math.max(min, Math.min(n, max));
}

function graphNodes(graph) {
    return Array.from(graph?._nodes || graph?.nodes || []);
}

function getLink(graph, id) {
    if (id == null) return null;
    const links = graph?.links;
    if (!links) return null;
    if (links instanceof Map) return links.get(id) || null;
    return links[id] || null;
}

function slotHasLink(slot, isOutput = false) {
    return isOutput ? Array.isArray(slot?.links) && slot.links.length > 0 : slot?.link != null;
}

function highestLinkedSlot(slots, isOutput = false) {
    let highest = -1;
    for (let i = 0; i < (slots?.length || 0); i++) {
        if (slotHasLink(slots[i], isOutput)) highest = i;
    }
    return highest;
}

function sanitizeName(value, fallback) {
    const name = String(value ?? "").trim();
    return name || fallback;
}

function makeUniqueName(name, used) {
    const base = sanitizeName(name, "channel");
    let candidate = base;
    let i = 1;
    while (used.has(candidate)) {
        candidate = `${base}_${i}`;
        i += 1;
    }
    used.add(candidate);
    return candidate;
}

function normalizeChannels(channels, count = DEFAULT_COUNT) {
    const result = Array.isArray(channels) ? channels.map((name, i) => sanitizeName(name, `value_${i + 1}`)) : [];
    while (result.length < count) result.push(`value_${result.length + 1}`);
    if (result.length > MAX_CHANNELS) result.length = MAX_CHANNELS;
    return result.length ? result : ["value_1"];
}

function channelWidgetName(index) {
    return `channel_${index + 1}`;
}

function providerEntries(graph, namespace, excludeNode = null, excludeIndex = -1) {
    const entries = [];
    for (const node of graphNodes(graph)) {
        if (node?.type !== SENDER_NODE_TYPE) continue;
        if (getNamespace(node) !== namespace) continue;
        const channels = getChannels(node);
        for (let i = 0; i < channels.length; i++) {
            if (node === excludeNode && i === excludeIndex) continue;
            entries.push({
                node,
                index: i,
                name: channels[i],
                input: node.inputs?.[i] || null,
            });
        }
    }
    return entries;
}

function findProvider(graph, namespace, channel) {
    return providerEntries(graph, namespace)
        .filter(entry => entry.name === channel)
        .sort((a, b) => {
            const aLinked = a.input?.link != null ? 0 : 1;
            const bLinked = b.input?.link != null ? 0 : 1;
            if (aLinked !== bLinked) return aLinked - bLinked;
            return Number(a.node.id || 0) - Number(b.node.id || 0);
        })[0] || null;
}

function getNamespace(node) {
    return sanitizeName(node.properties?.namespace, DEFAULT_NAMESPACE);
}

function setNamespace(node, namespace) {
    node.properties ??= {};
    node.properties.namespace = sanitizeName(namespace, DEFAULT_NAMESPACE);
    const widget = node.widgets?.find(w => w.name === "namespace");
    if (widget && widget.value !== node.properties.namespace) widget.value = node.properties.namespace;
    updateTitle(node);
}

function getChannels(node) {
    node.properties ??= {};
    node.properties.channels = normalizeChannels(node.properties.channels, DEFAULT_COUNT);
    return node.properties.channels;
}

function setChannels(node, channels) {
    node.properties ??= {};
    node.properties.channels = normalizeChannels(channels, channels?.length || DEFAULT_COUNT);
    const countWidget = node.widgets?.find(w => w.name === "count");
    if (countWidget) countWidget.value = node.properties.channels.length;
    updateTitle(node);
}

function updateTitle(node) {
    const prefix = node.type === SENDER_NODE_TYPE ? "Wireless V3 Input" : "Wireless V3 Output";
    node.title = `${prefix} [${getNamespace(node)}]`;
}

function getInputSourceType(node, index) {
    const input = node.inputs?.[index];
    const link = getLink(node.graph, input?.link);
    if (!link) return input?.type || "*";
    const sourceNode = node.graph?.getNodeById?.(link.origin_id);
    return sourceNode?.outputs?.[link.origin_slot]?.type || link.type || input?.type || "*";
}

function getOutputTargetType(node, index) {
    const output = node.outputs?.[index];
    const linkId = output?.links?.[0];
    const link = getLink(node.graph, linkId);
    if (!link) return output?.type || "*";
    const targetNode = node.graph?.getNodeById?.(link.target_id);
    return targetNode?.inputs?.[link.target_slot]?.type || link.type || output?.type || "*";
}

function getProviderType(entry) {
    if (!entry) return "*";
    return getInputSourceType(entry.node, entry.index) || "*";
}

function setNodeDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
}

function refreshNodeSize(node) {
    if (node.setSize && node.computeSize) {
        try { node.setSize(node.computeSize()); } catch (e) {}
    }
    setNodeDirty(node);
}

function syncReceivers(graph, namespace) {
    for (const node of graphNodes(graph)) {
        if (node?.type === RECEIVER_NODE_TYPE && getNamespace(node) === namespace) {
            node.syncSlots?.();
        }
    }
}

function syncProviderTypes(graph, namespace) {
    for (const node of graphNodes(graph)) {
        if (node?.type === SENDER_NODE_TYPE && getNamespace(node) === namespace) {
            node.syncSlots?.();
        }
    }
}

function installCrossGraphPatch() {
    if (app.__wuddWirelessCrossGraphPatched) return;

    const originalGraphToPrompt = app.graphToPrompt?.bind(app);
    if (!originalGraphToPrompt) return;

    app.graphToPrompt = async function (...args) {
        try {
            const subgraphNode = app.graph?._nodes?.find(n => typeof n.getInnerNodes === "function");
            if (!subgraphNode) return await originalGraphToPrompt(...args);

            const tempMap = new Map();
            const dtos = subgraphNode.getInnerNodes(tempMap, []);
            if (!dtos.length) return await originalGraphToPrompt(...args);

            const proto = Object.getPrototypeOf(dtos[0]);
            if (!proto?.resolveOutput || proto.resolveOutput.toString().includes("resolveVirtualOutput")) {
                app.__wuddWirelessCrossGraphPatched = true;
                return await originalGraphToPrompt(...args);
            }

            const DtoClass = proto.constructor;
            const originalResolveOutput = proto.resolveOutput;
            proto.resolveOutput = function (slot, type, visited) {
                if (typeof this.node?.resolveVirtualOutput === "function") {
                    const virtualSource = this.node.resolveVirtualOutput(slot);
                    if (virtualSource) {
                        const inputNodeDto = [...this.nodesByExecutionId.values()]
                            .find(dto => dto instanceof DtoClass && dto.node === virtualSource.node);
                        if (inputNodeDto) return inputNodeDto.resolveOutput(virtualSource.slot, type, visited);
                    }
                }
                return originalResolveOutput.call(this, slot, type, visited);
            };
            app.__wuddWirelessCrossGraphPatched = true;
            return await originalGraphToPrompt(...args);
        } catch (e) {
            console.warn("[Wudd] Wireless graphToPrompt patch failed:", e);
            return await originalGraphToPrompt(...args);
        }
    };
}

class WuddWirelessBase extends LiteGraph.LGraphNode {
    constructor(title) {
        super(title);
        this.isVirtualNode = true;
        this.serialize_widgets = false;
        this.properties ??= {};
        this.properties.namespace ??= DEFAULT_NAMESPACE;
        this.properties.channels = normalizeChannels(this.properties.channels, DEFAULT_COUNT);

        this.addWidget("text", "namespace", getNamespace(this), value => {
            setNamespace(this, value);
            this.validateChannelNames();
            this.syncSlots();
            syncReceivers(this.graph, getNamespace(this));
            syncProviderTypes(this.graph, getNamespace(this));
        });
        this.addWidget("number", "count", getChannels(this).length, value => {
            this.setCount(value);
        }, { min: 1, max: MAX_CHANNELS, step: 1, precision: 0 });
        this.syncSlots();
    }

    get countWidget() {
        return this.widgets?.find(w => w.name === "count");
    }

    setCount(value) {
        const channels = getChannels(this);
        const count = clampInt(value, 1, MAX_CHANNELS);
        while (channels.length < count) channels.push(`value_${channels.length + 1}`);
        if (channels.length > count) channels.length = count;
        setChannels(this, channels);
        this.syncSlots();
    }

    onConfigure() {
        this.properties ??= {};
        this.properties.namespace = sanitizeName(this.properties.namespace, DEFAULT_NAMESPACE);
        this.properties.channels = normalizeChannels(this.properties.channels, DEFAULT_COUNT);
        setNamespace(this, this.properties.namespace);
        this.syncSlots();
    }

    onAdded() {
        this.validateChannelNames();
        this.syncSlots();
    }

    clone() {
        const cloned = super.clone();
        cloned.properties = {
            ...cloned.properties,
            channels: [...getChannels(this)],
        };
        return cloned;
    }

    channelName(index) {
        return getChannels(this)[index] || `value_${index + 1}`;
    }

    ensureChannelWidget(index) {
        const widgetName = channelWidgetName(index);
        let widget = this.widgets?.find(w => w.__wuddWirelessChannelIndex === index);
        if (!widget) {
            widget = this.addWidget("text", widgetName, this.channelName(index), value => {
                const channels = getChannels(this);
                channels[index] = sanitizeName(value, `value_${index + 1}`);
                setChannels(this, channels);
                this.validateChannelNames(index);
                this.syncSlots();
                syncReceivers(this.graph, getNamespace(this));
            });
            widget.__wuddWirelessChannelIndex = index;
            widget.serialize = false;
        }
        widget.name = widgetName;
        widget.value = this.channelName(index);
        return widget;
    }

    removeExtraChannelWidgets(count) {
        for (let i = (this.widgets?.length || 0) - 1; i >= 0; i--) {
            const widget = this.widgets[i];
            if (widget?.__wuddWirelessChannelIndex != null && widget.__wuddWirelessChannelIndex >= count) {
                this.widgets.splice(i, 1);
            }
        }
    }

    validateChannelNames() {}
    syncSlots() {}
}

class WuddWirelessInput extends WuddWirelessBase {
    static title = "Wudd V3 Wireless Input";
    static category = CATEGORY;

    constructor(title = WuddWirelessInput.title) {
        super(title);
        this.type = SENDER_NODE_TYPE;
        updateTitle(this);
    }

    validateChannelNames(changedIndex = -1) {
        if (!this.graph || this.__validatingNames) return;
        this.__validatingNames = true;
        const channels = getChannels(this);
        const namespace = getNamespace(this);

        for (let i = 0; i < channels.length; i++) {
            const used = new Set(providerEntries(this.graph, namespace, this, i).map(entry => entry.name));
            for (let j = 0; j < i; j++) used.add(channels[j]);
            const unique = makeUniqueName(channels[i], used);
            if (unique !== channels[i]) {
                channels[i] = unique;
                if (changedIndex === i || changedIndex < 0) {
                    console.warn(`[Wudd] Wireless channel renamed to avoid conflict: ${unique}`);
                }
            }
        }

        setChannels(this, channels);
        this.__validatingNames = false;
    }

    syncSlots() {
        this.validateChannelNames();
        const channels = getChannels(this);
        const linkedMin = highestLinkedSlot(this.inputs, false) + 1;
        const count = Math.max(channels.length, linkedMin, 1);
        while (channels.length < count) channels.push(`value_${channels.length + 1}`);
        if (channels.length > count) channels.length = count;

        while ((this.inputs?.length || 0) < count) {
            const index = this.inputs?.length || 0;
            this.addInput(channels[index], "*");
        }

        while ((this.inputs?.length || 0) > count) {
            const last = this.inputs[this.inputs.length - 1];
            if (slotHasLink(last, false)) break;
            this.removeInput(this.inputs.length - 1);
        }

        for (let i = 0; i < (this.inputs?.length || 0); i++) {
            const name = channels[i] || `value_${i + 1}`;
            this.inputs[i].name = name;
            this.inputs[i].type = this.inputs[i].link != null ? getInputSourceType(this, i) : (this.inputs[i].type || "*");
            this.ensureChannelWidget(i);
        }

        this.removeExtraChannelWidgets(this.inputs?.length || 0);
        setChannels(this, channels.slice(0, this.inputs?.length || 0));
        refreshNodeSize(this);
    }

    onConnectionsChange(type, index, connected) {
        if (type === INPUT) {
            if (connected && this.inputs?.[index]) {
                this.inputs[index].type = getInputSourceType(this, index);
            } else if (this.inputs?.[index]) {
                this.inputs[index].type = "*";
            }
            syncReceivers(this.graph, getNamespace(this));
            setNodeDirty(this);
        }
    }

    getExtraMenuOptions(_, options) {
        options.unshift(
            {
                content: "Wudd: Add channel",
                callback: () => this.setCount(getChannels(this).length + 1),
            },
            {
                content: "Wudd: Create matching output",
                callback: () => {
                    const receiver = LiteGraph.createNode(RECEIVER_NODE_TYPE);
                    if (!receiver) return;
                    receiver.pos = [this.pos[0] + this.size[0] + 80, this.pos[1]];
                    this.graph.add(receiver);
                    setNamespace(receiver, getNamespace(this));
                    setChannels(receiver, [...getChannels(this)]);
                    receiver.syncSlots?.();
                    app.canvas?.selectNode(receiver, false);
                    app.canvas?.setDirty(true, true);
                },
            },
        );
    }
}

class WuddWirelessOutput extends WuddWirelessBase {
    static title = "Wudd V3 Wireless Output";
    static category = CATEGORY;

    constructor(title = WuddWirelessOutput.title) {
        super(title);
        this.type = RECEIVER_NODE_TYPE;
        updateTitle(this);
    }

    onAdded() {
        const channels = getChannels(this);
        const isDefault = channels.every((name, i) => name === `value_${i + 1}`);
        const entries = providerEntries(this.graph, getNamespace(this));
        if (isDefault && entries.length) {
            setChannels(this, entries.map(entry => entry.name));
        }
        super.onAdded?.();
        this.syncSlots();
    }

    validateChannelNames() {
        const channels = getChannels(this);
        const used = new Set();
        for (let i = 0; i < channels.length; i++) {
            channels[i] = makeUniqueName(channels[i], used);
        }
        setChannels(this, channels);
    }

    syncSlots() {
        this.validateChannelNames();
        const channels = getChannels(this);
        const linkedMin = highestLinkedSlot(this.outputs, true) + 1;
        const count = Math.max(channels.length, linkedMin, 1);
        while (channels.length < count) channels.push(`value_${channels.length + 1}`);
        if (channels.length > count) channels.length = count;

        while ((this.outputs?.length || 0) < count) {
            const index = this.outputs?.length || 0;
            this.addOutput(channels[index], "*");
        }

        while ((this.outputs?.length || 0) > count) {
            const last = this.outputs[this.outputs.length - 1];
            if (slotHasLink(last, true)) break;
            this.removeOutput(this.outputs.length - 1);
        }

        for (let i = 0; i < (this.outputs?.length || 0); i++) {
            const name = channels[i] || `value_${i + 1}`;
            const provider = findProvider(this.graph, getNamespace(this), name);
            this.outputs[i].name = name;
            this.outputs[i].type = provider ? getProviderType(provider) : getOutputTargetType(this, i);
            this.ensureChannelWidget(i);
        }

        this.removeExtraChannelWidgets(this.outputs?.length || 0);
        setChannels(this, channels.slice(0, this.outputs?.length || 0));
        refreshNodeSize(this);
    }

    onConnectionsChange(type) {
        if (type === OUTPUT) {
            this.syncSlots();
        }
    }

    getInputLink(slot) {
        const channel = this.channelName(slot);
        const provider = findProvider(this.graph, getNamespace(this), channel);
        if (!provider?.input || provider.input.link == null) return null;
        return getLink(provider.node.graph, provider.input.link);
    }

    resolveVirtualOutput(slot) {
        const link = this.getInputLink(slot);
        if (!link) return undefined;
        const providerGraph = this.graph;
        const sourceNode = providerGraph?.getNodeById?.(link.origin_id);
        if (!sourceNode) return undefined;
        return { node: sourceNode, slot: link.origin_slot };
    }

    refreshFromProviders() {
        const entries = providerEntries(this.graph, getNamespace(this));
        if (!entries.length) return;
        setChannels(this, entries.map(entry => entry.name));
        this.syncSlots();
    }

    getExtraMenuOptions(_, options) {
        options.unshift(
            {
                content: "Wudd: Add channel",
                callback: () => this.setCount(getChannels(this).length + 1),
            },
            {
                content: "Wudd: Refresh from inputs",
                callback: () => this.refreshFromProviders(),
            },
        );
    }
}

app.registerExtension({
    name: "WuddV3.Wireless",
    setup() {
        installCrossGraphPatch();
    },
    registerCustomNodes() {
        LiteGraph.registerNodeType(SENDER_NODE_TYPE, WuddWirelessInput);
        LiteGraph.registerNodeType(RECEIVER_NODE_TYPE, WuddWirelessOutput);
    },
});
