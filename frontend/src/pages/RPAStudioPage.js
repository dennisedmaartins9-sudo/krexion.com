import React, { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  ReactFlowProvider,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  Play,
  Save,
  Plus,
  Trash2,
  Download,
  Upload,
  ChevronLeft,
  Layers,
  X,
  Settings as SettingsIcon,
  Activity,
  Zap,
  Search,
  Copy,
  ArrowLeft,
  AlertCircle,
  Code,
  Variable,
  ClipboardCopy,
} from "lucide-react";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const authH = () => ({
  Authorization: `Bearer ${localStorage.getItem("token")}`,
  "Content-Type": "application/json",
});

// Inline node component — small, color-coded, shows type + first param value.
// 2026-06: added explicit source/target Handles (the small dots on the
// left/right edges of the node) so users can DRAG one node onto another
// to draw an edge. Without these handles ReactFlow's onConnect never
// fires — that was THE reason the canvas felt "unconnectable".
const FlowNode = ({ data, selected }) => (
  <div
    style={{
      background: data.color || "#1e293b",
      color: "#fff",
      borderRadius: 10,
      padding: "10px 14px",
      minWidth: 160,
      border: (selected || data.selected) ? "2px solid #60a5fa" : "1px solid rgba(255,255,255,.15)",
      boxShadow: "0 6px 16px rgba(0,0,0,.4)",
      fontFamily: "ui-sans-serif, system-ui",
      position: "relative",
    }}
    data-testid={`rpa-node-${data.type}`}
  >
    {/* Target handle — incoming edges land here (left side) */}
    <Handle
      type="target"
      position={Position.Left}
      style={{
        background: "#60a5fa",
        width: 10,
        height: 10,
        border: "2px solid #0f172a",
      }}
      data-testid={`rpa-node-${data.type}-target`}
    />
    <div style={{ fontWeight: 600, fontSize: 13, opacity: 0.95 }}>{data.label || data.type}</div>
    <div style={{ fontSize: 11, opacity: 0.75, marginTop: 4, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
      {data.summary || data.type}
    </div>
    {/* Source handle — drag from here onto the next node's left handle
        to draw an edge / sequence link */}
    <Handle
      type="source"
      position={Position.Right}
      style={{
        background: "#22c55e",
        width: 10,
        height: 10,
        border: "2px solid #0f172a",
      }}
      data-testid={`rpa-node-${data.type}-source`}
    />
  </div>
);

const nodeTypes = { rpa: FlowNode };

export default function RPAStudioPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [workflow, setWorkflow] = useState(null);
  const [catalog, setCatalog] = useState({ categories: [] });
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [search, setSearch] = useState("");
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState(null);
  const [runEvents, setRunEvents] = useState([]);
  const [runVariables, setRunVariables] = useState({});
  const [runPanelTab, setRunPanelTab] = useState("events"); // "events" | "variables"
  const [runStatus, setRunStatus] = useState(null);
  const [showJsonEditor, setShowJsonEditor] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [saving, setSaving] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showRunPanel, setShowRunPanel] = useState(false);
  const reactFlowWrapper = useRef(null);
  const [rfInstance, setRfInstance] = useState(null);
  const [livePreview, setLivePreview] = useState(null);
  const liveImgRef = useRef(null);

  // Load catalog + workflow
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/rpa/node-catalog`, { headers: authH() });
        if (r.ok) {
          setCatalog(await r.json());
        }
      } catch {}
    })();
  }, []);

  useEffect(() => {
    if (!id || id === "new") {
      const params = new URLSearchParams(location.search || "");
      const bpId = (params.get("browser_profile_id") || "").trim();
      const bpName = (params.get("name") || "").trim();
      const baseSettings = bpId
        ? { browser_profile_id: bpId, headless: false }
        : {};
      setWorkflow({
        name: bpName ? `Profile: ${bpName}` : "Untitled Workflow",
        nodes: [],
        edges: [],
        settings: baseSettings,
        variables: {},
      });
      setNodes([]);
      setEdges([]);
      if (bpId) {
        toast.success(`Linked Browser Profile ${bpId.slice(0, 8)}…`);
        setShowSettings(true);
      }
      return;
    }
    (async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/rpa/workflows/${id}`, { headers: authH() });
        if (!r.ok) {
          toast.error("Workflow not found");
          navigate("/rpa-studio");
          return;
        }
        const wf = await r.json();
        const params = new URLSearchParams(location.search || "");
        const bpId = (params.get("browser_profile_id") || "").trim();
        if (bpId) {
          wf.settings = { ...(wf.settings || {}), browser_profile_id: bpId, headless: false };
          toast.success(`Linked Browser Profile ${bpId.slice(0, 8)}…`);
          setShowSettings(true);
        }
        setWorkflow(wf);
        setNodes(deserializeNodes(wf.nodes || [], catalog));
        setEdges(deserializeEdges(wf.edges || []));
      } catch (e) {
        toast.error(`Load failed: ${e.message}`);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, location.search]);

  // Build a lookup of {type: {label, color, category}} from catalog
  const typeLookup = useMemo(() => {
    const out = {};
    (catalog.categories || []).forEach((cat) => {
      (cat.nodes || []).forEach((n) => {
        out[n.type] = { label: n.label, color: cat.color, category: cat.key, params: n.params };
      });
    });
    return out;
  }, [catalog]);

  const onNodesChange = useCallback((changes) => setNodes((nds) => applyNodeChanges(changes, nds)), []);
  const onEdgesChange = useCallback((changes) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback(
    (connection) => setEdges((eds) => addEdge({ ...connection, animated: true, style: { stroke: "#60a5fa", strokeWidth: 2 } }, eds)),
    []
  );

  const addNode = useCallback(
    (nodeType) => {
      const typeInfo = typeLookup[nodeType] || {};
      const newId = `n_${Math.random().toString(36).slice(2, 9)}`;
      // 2026-06: Auto-position the new node to the RIGHT of the currently
      // selected one (or last-added one) and auto-create an edge from
      // selected → new. This gives users the "click click click → sequence"
      // workflow they expected, without making them drag from handles every
      // time. They can still drag from the green handle to re-route.
      const prevId = selectedNodeId;
      const prevNode = prevId ? nodes.find((n) => n.id === prevId) : null;
      const basePos = prevNode?.position || { x: 200, y: 100 };
      const newPos = prevNode
        ? { x: basePos.x + 220, y: basePos.y + (Math.random() * 20 - 10) }
        : { x: 200 + Math.random() * 250, y: 100 + Math.random() * 250 };
      const newNode = {
        id: newId,
        type: "rpa",
        position: newPos,
        data: {
          type: nodeType,
          label: typeInfo.label || nodeType,
          color: typeInfo.color || "#1e293b",
          params: {},
          on_error: "skip",
          summary: nodeType,
        },
      };
      setNodes((nds) => [...nds, newNode]);
      if (prevId && prevId !== newId) {
        // Auto-connect prev → new (skip if user already has an outgoing
        // edge from prev — they probably want a different topology).
        setEdges((eds) => {
          const hasOut = eds.some((e) => e.source === prevId);
          if (hasOut) return eds;
          return addEdge(
            {
              source: prevId,
              target: newId,
              animated: true,
              style: { stroke: "#60a5fa", strokeWidth: 2 },
            },
            eds
          );
        });
      }
      setSelectedNodeId(newId);
      toast.success(`Added: ${typeInfo.label || nodeType}`);
    },
    [typeLookup, selectedNodeId, nodes]
  );

  const deleteNode = (nodeId) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId));
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
    if (selectedNodeId === nodeId) setSelectedNodeId(null);
  };

  const updateNodeParam = (nodeId, key, value) => {
    setNodes((nds) =>
      nds.map((n) => {
        if (n.id !== nodeId) return n;
        const newParams = { ...(n.data.params || {}), [key]: value };
        // Build a friendly 1-line summary
        const firstVal = Object.values(newParams)[0];
        return {
          ...n,
          data: {
            ...n.data,
            params: newParams,
            summary: firstVal ? String(firstVal).slice(0, 30) : n.data.type,
          },
        };
      })
    );
  };

  const updateNodeOnError = (nodeId, val) => {
    setNodes((nds) => nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, on_error: val } } : n)));
  };

  const saveWorkflow = async () => {
    if (!workflow) return;
    setSaving(true);
    try {
      const serialized = {
        name: workflow.name || "Untitled",
        description: workflow.description || "",
        nodes: nodes.map(serializeNode),
        edges: edges.map((e) => ({ from: e.source, to: e.target, label: e.label })),
        settings: workflow.settings || {},
        variables: workflow.variables || {},
      };
      let r;
      if (workflow.id) {
        r = await fetch(`${BACKEND_URL}/api/rpa/workflows/${workflow.id}`, {
          method: "PATCH",
          headers: authH(),
          body: JSON.stringify(serialized),
        });
      } else {
        r = await fetch(`${BACKEND_URL}/api/rpa/workflows`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify(serialized),
        });
      }
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setWorkflow(d);
      toast.success("Saved ✓");
      if (!workflow.id) navigate(`/rpa-studio/${d.id}`, { replace: true });
    } catch (e) {
      toast.error(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const runWorkflow = async () => {
    if (!workflow?.id) {
      toast.error("Save the workflow first");
      return;
    }
    setRunning(true);
    setRunEvents([]);
    setRunStatus("starting");
    setShowRunPanel(true);
    try {
      const r = await fetch(`${BACKEND_URL}/api/rpa/workflows/${workflow.id}/run`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setRunId(d.run_id);
      toast.success(`Run started: ${d.run_id}`);
    } catch (e) {
      toast.error(`Run failed: ${e.message}`);
      setRunning(false);
    }
  };

  // Poll run status
  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/api/rpa/runs/${runId}/live`, { headers: authH() });
        if (!r.ok) return;
        const d = await r.json();
        setRunEvents(d.events || []);
        setRunVariables(d.variables || {});
        setRunStatus(d.status);
        if (d.has_screenshot) {
          setLivePreview(`${BACKEND_URL}/api/rpa/runs/${runId}/screenshot?t=${encodeURIComponent(localStorage.getItem("token"))}&ts=${Date.now()}`);
        }
        if (["completed", "failed", "cancelled"].includes(d.status)) {
          setRunning(false);
          if (d.status === "completed") toast.success("Run completed ✓");
          else if (d.status === "failed") toast.error(`Run failed: ${d.error_message || "unknown"}`);
        }
      } catch {}
    };
    poll();
    const t = setInterval(poll, 1500);
    return () => clearInterval(t);
  }, [runId]);

  const stopRun = async () => {
    if (!runId) return;
    await fetch(`${BACKEND_URL}/api/rpa/runs/${runId}/stop`, { method: "POST", headers: authH() });
    setRunning(false);
    toast.info("Run stopped");
  };

  const exportJson = () => {
    if (!workflow?.id) {
      toast.error("Save first");
      return;
    }
    fetch(`${BACKEND_URL}/api/rpa/workflows/${workflow.id}/export`, { headers: authH() })
      .then((r) => r.json())
      .then((d) => {
        const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${(workflow.name || "workflow").replace(/[^a-z0-9]/gi, "_")}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
      });
  };

  // Filter palette nodes by search
  const filteredCategories = useMemo(() => {
    if (!search.trim()) return catalog.categories || [];
    const q = search.toLowerCase();
    return (catalog.categories || [])
      .map((cat) => ({
        ...cat,
        nodes: (cat.nodes || []).filter((n) => n.label.toLowerCase().includes(q) || n.type.toLowerCase().includes(q)),
      }))
      .filter((cat) => cat.nodes.length > 0);
  }, [search, catalog]);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const paramSpec = selectedNode ? typeLookup[selectedNode.data.type]?.params || [] : [];

  return (
    <ReactFlowProvider>
      <div className="flex flex-col h-screen bg-slate-950 text-white" data-testid="rpa-studio-page">
        {/* Top toolbar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800 bg-slate-900">
          <button
            onClick={() => navigate("/rpa-studio")}
            className="p-2 rounded hover:bg-slate-800"
            data-testid="rpa-back-btn"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <input
            value={workflow?.name || ""}
            onChange={(e) => setWorkflow({ ...workflow, name: e.target.value })}
            placeholder="Workflow name"
            className="bg-slate-800 px-3 py-1.5 rounded text-sm w-72 outline-none focus:ring-2 focus:ring-blue-500"
            data-testid="rpa-name-input"
          />
          <span className="text-xs text-slate-400">
            {nodes.length} nodes · {edges.length} edges {workflow?.id && `· v${workflow.version}`}
          </span>
          <div className="flex-1" />
          <button onClick={() => setShowSettings(!showSettings)} className="p-2 rounded hover:bg-slate-800" title="Settings" data-testid="rpa-settings-btn">
            <SettingsIcon className="w-4 h-4" />
          </button>
          <button onClick={exportJson} className="p-2 rounded hover:bg-slate-800" title="Export JSON" data-testid="rpa-export-btn">
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={saveWorkflow}
            disabled={saving}
            className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-sm flex items-center gap-1.5 disabled:opacity-50"
            data-testid="rpa-save-btn"
          >
            <Save className="w-3.5 h-3.5" />
            {saving ? "Saving..." : "Save"}
          </button>
          <button
            onClick={running ? stopRun : runWorkflow}
            disabled={!workflow?.id}
            className={`px-3 py-1.5 rounded text-sm flex items-center gap-1.5 ${running ? "bg-red-600 hover:bg-red-500" : "bg-emerald-600 hover:bg-emerald-500"} disabled:opacity-50`}
            data-testid="rpa-run-btn"
          >
            {running ? <X className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            {running ? "Stop" : "Run"}
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Left: Node Palette */}
          <div className="w-64 border-r border-slate-800 bg-slate-900 overflow-y-auto" data-testid="rpa-palette">
            <div className="p-3 sticky top-0 bg-slate-900 z-10 border-b border-slate-800">
              <div className="flex items-center gap-2 mb-2">
                <Layers className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-semibold">Node Palette</h3>
              </div>
              <div className="relative">
                <Search className="absolute left-2 top-2 w-3.5 h-3.5 text-slate-500" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search nodes…"
                  className="w-full bg-slate-800 pl-7 pr-2 py-1.5 rounded text-xs outline-none focus:ring-2 focus:ring-blue-500"
                  data-testid="rpa-palette-search"
                />
              </div>
            </div>
            <div className="p-2 space-y-3">
              {filteredCategories.map((cat) => (
                <div key={cat.key}>
                  <div className="text-xs font-semibold mb-1 px-2 flex items-center gap-1.5" style={{ color: cat.color }}>
                    <span className="w-2 h-2 rounded-full" style={{ background: cat.color }} />
                    {cat.label} ({cat.nodes.length})
                  </div>
                  <div className="space-y-1">
                    {cat.nodes.map((n) => (
                      <button
                        key={n.type}
                        onClick={() => addNode(n.type)}
                        className="w-full text-left px-3 py-1.5 text-xs rounded bg-slate-800 hover:bg-slate-700 flex items-center justify-between transition-colors"
                        data-testid={`rpa-palette-add-${n.type}`}
                      >
                        <span>{n.label}</span>
                        <Plus className="w-3 h-3 opacity-50" />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              {filteredCategories.length === 0 && (
                <div className="text-xs text-slate-500 p-3">No matching nodes</div>
              )}
            </div>
          </div>

          {/* Center: Canvas */}
          <div className="flex-1 relative" ref={reactFlowWrapper}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              onPaneClick={() => setSelectedNodeId(null)}
              nodeTypes={nodeTypes}
              fitView
              onInit={setRfInstance}
              defaultEdgeOptions={{ animated: true, style: { stroke: "#60a5fa", strokeWidth: 2 } }}
              data-testid="rpa-canvas"
            >
              <Background color="#1e293b" gap={20} />
              <Controls />
              <MiniMap nodeColor={(n) => n.data?.color || "#475569"} maskColor="rgba(0,0,0,.5)" />
            </ReactFlow>
            {nodes.length === 0 && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-slate-500">
                <Zap className="w-12 h-12 mb-3 opacity-40" />
                <div className="text-lg mb-1">Empty workflow</div>
                <div className="text-sm">← Click a node from the palette to start</div>
              </div>
            )}
          </div>

          {/* Right: Inspector */}
          <div className="w-80 border-l border-slate-800 bg-slate-900 overflow-y-auto" data-testid="rpa-inspector">
            {selectedNode ? (
              <div className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full" style={{ background: selectedNode.data.color }} />
                    {selectedNode.data.label}
                  </h3>
                  <button
                    onClick={() => deleteNode(selectedNode.id)}
                    className="p-1.5 rounded hover:bg-red-500/20 text-red-400"
                    title="Delete node"
                    data-testid="rpa-delete-node-btn"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="text-xs text-slate-500 mb-3 font-mono">{selectedNode.data.type}</div>

                {/* Param fields */}
                <div className="space-y-3">
                  {paramSpec.map((paramName) => (
                    <div key={paramName}>
                      <label className="block text-xs text-slate-400 mb-1 capitalize">{paramName.replace(/_/g, " ")}</label>
                      {paramName === "script" || paramName === "body" || paramName === "template" ? (
                        <textarea
                          value={selectedNode.data.params?.[paramName] || ""}
                          onChange={(e) => updateNodeParam(selectedNode.id, paramName, e.target.value)}
                          rows={4}
                          className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs font-mono outline-none focus:ring-2 focus:ring-blue-500"
                          data-testid={`rpa-param-${paramName}`}
                        />
                      ) : (
                        <input
                          value={selectedNode.data.params?.[paramName] || ""}
                          onChange={(e) => updateNodeParam(selectedNode.id, paramName, e.target.value)}
                          placeholder={paramHint(paramName)}
                          className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs outline-none focus:ring-2 focus:ring-blue-500"
                          data-testid={`rpa-param-${paramName}`}
                        />
                      )}
                    </div>
                  ))}
                  {paramSpec.length === 0 && (
                    <div className="text-xs text-slate-500">This node has no parameters</div>
                  )}
                </div>

                {/* On error */}
                <div className="mt-4 pt-3 border-t border-slate-800">
                  <label className="block text-xs text-slate-400 mb-1">On Error</label>
                  <select
                    value={selectedNode.data.on_error || "skip"}
                    onChange={(e) => updateNodeOnError(selectedNode.id, e.target.value)}
                    className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs outline-none focus:ring-2 focus:ring-blue-500"
                    data-testid="rpa-on-error-select"
                  >
                    <option value="skip">Skip — continue to next step</option>
                    <option value="stop">Stop — abort workflow</option>
                    <option value="retry">Retry (3 attempts)</option>
                  </select>
                </div>
              </div>
            ) : (
              <div className="p-6 text-center text-slate-500">
                <Layers className="w-8 h-8 mx-auto mb-2 opacity-40" />
                <div className="text-sm">Select a node to configure</div>
              </div>
            )}

            {/* Settings drawer */}
            {showSettings && (
              <div className="border-t border-slate-800 p-4 bg-slate-950/50">
                <h4 className="text-xs font-semibold text-blue-400 mb-2">Workflow Settings</h4>
                <label className="block text-xs text-slate-400 mb-1">Browser Profile ID</label>
                <input
                  type="text"
                  value={workflow?.settings?.browser_profile_id ?? ""}
                  onChange={(e) => setWorkflow({
                    ...workflow,
                    settings: {
                      ...(workflow.settings || {}),
                      browser_profile_id: e.target.value.slice(0, 80),
                    },
                  })}
                  className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs mb-2"
                  placeholder="from Browser Profiles → RPA"
                  data-testid="rpa-settings-browser-profile-id"
                />
                <label className="block text-xs text-slate-400 mb-1">Headless</label>
                <select
                  value={workflow?.settings?.headless ?? true}
                  onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), headless: e.target.value === "true" } })}
                  className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs mb-2"
                  data-testid="rpa-settings-headless"
                >
                  <option value="true">Headless (no visible window)</option>
                  <option value="false">Headed (visible browser)</option>
                </select>
                <label className="block text-xs text-slate-400 mb-1">Max runtime (sec)</label>
                <input
                  type="number"
                  value={workflow?.settings?.max_runtime_seconds ?? 3600}
                  onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), max_runtime_seconds: Number(e.target.value) } })}
                  className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs"
                />

                {/* ── 2026-02 Anti-Detect Phase 1 ── */}
                <div className="mt-4 pt-3 border-t border-slate-800">
                  <h4 className="text-xs font-semibold text-fuchsia-400 mb-2">Anti-Detect (Phase 1)</h4>

                  <label className="block text-xs text-slate-400 mb-1">Pacing (visits / hour)</label>
                  <input
                    type="number"
                    min={0}
                    max={3600}
                    value={workflow?.settings?.pacing_per_hour ?? 0}
                    onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), pacing_per_hour: Math.max(0, Math.min(3600, Number(e.target.value) || 0)) } })}
                    className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs mb-1"
                    placeholder="0 = no pacing jitter"
                    data-testid="rpa-settings-pacing-per-hour"
                  />
                  <p className="text-[10px] text-slate-500 mb-2">
                    Log-normal jitter on run start. 0 = run immediately. 10–60 typical for batches.
                  </p>

                  <label className="block text-xs text-slate-400 mb-1">Identity Label</label>
                  <input
                    type="text"
                    value={workflow?.settings?.identity_label ?? ""}
                    onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), identity_label: e.target.value.slice(0, 120) } })}
                    className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs mb-1"
                    placeholder="(blank = fresh identity per run)"
                    data-testid="rpa-settings-identity-label"
                  />
                  <p className="text-[10px] text-slate-500 mb-2">
                    Persistent identity (cookies + fingerprint) across runs with this label.
                  </p>

                  <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!workflow?.settings?.tls_prewarm}
                      onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), tls_prewarm: e.target.checked } })}
                      className="rounded"
                      data-testid="rpa-settings-tls-prewarm"
                    />
                    <span>TLS / JA3 Pre-warm (Chrome impersonation)</span>
                  </label>
                  <p className="text-[10px] text-slate-500 mt-1">
                    First Goto fetches via curl_cffi (real Chrome TLS) and seeds cookies onto context.
                    Bypasses Cloudflare BM / DataDome / Akamai on cold visits.
                  </p>
                </div>

                {/* ── 2026-02 Step 5 — Phase 3+4 parity (Big-1) ── */}
                <div className="mt-4 pt-3 border-t border-slate-800">
                  <h4 className="text-xs font-semibold text-sky-400 mb-2">Phase 3+4</h4>

                  <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer mb-2">
                    <input
                      type="checkbox"
                      checked={!!workflow?.settings?.proxy_chain_enabled}
                      onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), proxy_chain_enabled: e.target.checked } })}
                      className="rounded"
                      data-testid="rpa-settings-proxy-chain"
                    />
                    <span>Multi-Hop Proxy Chain (Tor → exit)</span>
                  </label>

                  <label className="block text-xs text-slate-400 mb-1">Browser Binary</label>
                  <select
                    value={workflow?.settings?.browser_variant ?? "auto"}
                    onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), browser_variant: e.target.value } })}
                    className="w-full bg-slate-800 px-2 py-1.5 rounded text-xs mb-2"
                    data-testid="rpa-settings-browser-variant"
                  >
                    <option value="auto">Auto</option>
                    <option value="chromium">Full Chromium</option>
                    <option value="brave">Brave</option>
                    <option value="headless-shell">Headless-Shell</option>
                    <option value="rotate">Rotate</option>
                  </select>

                  <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer mb-2">
                    <input
                      type="checkbox"
                      checked={!!workflow?.settings?.behavioral_bio_enabled}
                      onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), behavioral_bio_enabled: e.target.checked } })}
                      className="rounded"
                      data-testid="rpa-settings-behavioral-bio"
                    />
                    <span>Behavioral Biometrics (paranoia mode)</span>
                  </label>

                  <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!workflow?.settings?.ip_warmup_enabled}
                      onChange={(e) => setWorkflow({ ...workflow, settings: { ...(workflow.settings || {}), ip_warmup_enabled: e.target.checked } })}
                      className="rounded"
                      data-testid="rpa-settings-ip-warmup"
                    />
                    <span>IP Warm-up (Google/Wikipedia)</span>
                  </label>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Run panel (bottom overlay when running) */}
        {showRunPanel && (
          <div className="absolute bottom-0 left-64 right-80 max-h-96 border-t border-slate-700 bg-slate-950/95 backdrop-blur" data-testid="rpa-run-panel">
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800">
              <div className="flex items-center gap-3 text-sm">
                <Activity className={`w-4 h-4 ${running ? "text-emerald-400 animate-pulse" : "text-slate-400"}`} />
                <span className="font-semibold">Run: {runId?.slice(0, 16)}…</span>
                <span className={`px-2 py-0.5 rounded text-xs ${
                  runStatus === "completed" ? "bg-emerald-500/20 text-emerald-300" :
                  runStatus === "failed" ? "bg-red-500/20 text-red-300" :
                  runStatus === "running" ? "bg-blue-500/20 text-blue-300" :
                  "bg-slate-700 text-slate-400"
                }`}>{runStatus}</span>
              </div>
              <button onClick={() => setShowRunPanel(false)} className="p-1 hover:bg-slate-800 rounded">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex h-72">
              {/* Live preview */}
              <div className="w-1/2 border-r border-slate-800 p-2 overflow-hidden">
                <div className="text-xs text-slate-400 mb-1">Live Browser View</div>
                {livePreview ? (
                  <img
                    ref={liveImgRef}
                    src={livePreview}
                    alt="live"
                    className="w-full h-full object-contain rounded border border-slate-700"
                    data-testid="rpa-run-live-image"
                    onError={() => {}}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-slate-600 text-sm">
                    No preview yet
                  </div>
                )}
              </div>
              {/* Event log / Variables Inspector — tabbed */}
              <div className="w-1/2 flex flex-col">
                <div className="flex items-center gap-1 px-2 pt-2 border-b border-slate-800">
                  <button
                    onClick={() => setRunPanelTab("events")}
                    className={`px-3 py-1.5 text-xs rounded-t transition-colors ${
                      runPanelTab === "events"
                        ? "bg-slate-800 text-white border-b-2 border-blue-500"
                        : "text-slate-400 hover:text-white hover:bg-slate-800/60"
                    }`}
                    data-testid="rpa-run-tab-events"
                  >
                    <Activity className="w-3 h-3 inline mr-1.5" />
                    Events ({runEvents.length})
                  </button>
                  <button
                    onClick={() => setRunPanelTab("variables")}
                    className={`px-3 py-1.5 text-xs rounded-t transition-colors ${
                      runPanelTab === "variables"
                        ? "bg-slate-800 text-white border-b-2 border-emerald-500"
                        : "text-slate-400 hover:text-white hover:bg-slate-800/60"
                    }`}
                    data-testid="rpa-run-tab-variables"
                  >
                    <Variable className="w-3 h-3 inline mr-1.5" />
                    Variables ({Object.keys(runVariables).length})
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto p-2 text-xs font-mono">
                  {runPanelTab === "events" && (
                    <>
                      {runEvents.length === 0 && <div className="text-slate-500">No events yet</div>}
                      {runEvents.map((ev, i) => (
                        <div
                          key={i}
                          className={`px-2 py-1 mb-0.5 rounded text-xs ${
                            ev.status === "ok" ? "bg-emerald-900/20 text-emerald-300" :
                            ev.status === "error" ? "bg-red-900/20 text-red-300" :
                            ev.status === "running" ? "bg-blue-900/20 text-blue-300" :
                            "bg-slate-800/50 text-slate-400"
                          }`}
                          data-testid={`rpa-run-event-${i}`}
                        >
                          <span className="opacity-60">[{ev.step || i + 1}]</span> {ev.type}
                          {ev.status === "error" && <span className="block text-red-400 mt-0.5">⚠ {ev.error}</span>}
                        </div>
                      ))}
                    </>
                  )}
                  {runPanelTab === "variables" && (
                    <VariablesInspector variables={runVariables} />
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </ReactFlowProvider>
  );
}

// ── Variables Inspector ──────────────────────────────────────────────
// Renders a live key→value table of workflow variables with copy-to-clipboard
// per cell and type-aware formatting (string/number/bool/object/array).
function VariablesInspector({ variables }) {
  const entries = Object.entries(variables || {});
  if (entries.length === 0) {
    return (
      <div className="text-slate-500 px-2 py-4 text-center">
        <Variable className="w-6 h-6 mx-auto mb-2 opacity-30" />
        No variables yet — they'll appear here as the run sets them.
      </div>
    );
  }
  const copy = (val) => {
    try {
      navigator.clipboard.writeText(typeof val === "string" ? val : JSON.stringify(val, null, 2));
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Copy failed");
    }
  };
  const renderValue = (v) => {
    if (v === null || v === undefined) return <span className="text-slate-500">null</span>;
    if (typeof v === "boolean") return <span className="text-amber-400">{String(v)}</span>;
    if (typeof v === "number") return <span className="text-blue-400">{v}</span>;
    if (typeof v === "string") {
      if (v.startsWith("data:image/")) {
        return <span className="text-purple-400">[image · {v.length} chars]</span>;
      }
      return <span className="text-emerald-300 break-all">{v.length > 200 ? v.slice(0, 200) + "…" : v}</span>;
    }
    return <span className="text-cyan-300 break-all">{JSON.stringify(v).slice(0, 300)}</span>;
  };
  const typeOf = (v) => {
    if (v === null || v === undefined) return "null";
    if (Array.isArray(v)) return `array(${v.length})`;
    return typeof v;
  };
  return (
    <div className="space-y-1">
      {entries.map(([key, val]) => (
        <div
          key={key}
          className="bg-slate-800/40 hover:bg-slate-800/70 rounded px-2 py-1.5 group"
          data-testid={`rpa-var-${key}`}
        >
          <div className="flex items-center gap-2 text-xs">
            <code className="text-emerald-400 font-semibold flex-shrink-0">{key}</code>
            <span className="text-slate-600 text-[10px]">{typeOf(val)}</span>
            <div className="flex-1" />
            <button
              onClick={() => copy(val)}
              className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-slate-700"
              title="Copy value"
              data-testid={`rpa-var-copy-${key}`}
            >
              <ClipboardCopy className="w-3 h-3" />
            </button>
          </div>
          <div className="text-xs mt-0.5 pl-2 border-l-2 border-slate-700">{renderValue(val)}</div>
        </div>
      ))}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────
function paramHint(name) {
  const hints = {
    url: "https://example.com",
    selector: "#id  .class  input[name='x']",
    value: "{{var}} or literal",
    text: "Thank you",
    contains: "/success",
    times: "5",
    ms: "1000",
    timeout: "15000",
    pattern: ".*?(\\d+)",
    key: "save_to_var_name",
    save_to: "var_name",
    prompt: "Summarize this page",
    provider: "openai | anthropic | gemini",
    model: "gpt-4o-mini",
  };
  return hints[name] || "";
}

function deserializeNodes(nodesArr, catalog) {
  const typeMap = {};
  (catalog?.categories || []).forEach((cat) => {
    (cat.nodes || []).forEach((n) => {
      typeMap[n.type] = { label: n.label, color: cat.color };
    });
  });
  return nodesArr.map((n) => ({
    id: n.id,
    type: "rpa",
    position: n.position || { x: 100, y: 100 },
    data: {
      type: n.type,
      label: typeMap[n.type]?.label || n.type,
      color: typeMap[n.type]?.color || "#1e293b",
      params: n.params || {},
      on_error: n.on_error || "skip",
      body: n.body || [],
      branches: n.branches || {},
      summary: Object.values(n.params || {})[0] ? String(Object.values(n.params || {})[0]).slice(0, 30) : n.type,
    },
  }));
}

function deserializeEdges(edgesArr) {
  return edgesArr.map((e, i) => ({
    id: e.id || `e_${i}_${e.from}_${e.to}`,
    source: e.from || e.source,
    target: e.to || e.target,
    label: e.label,
    animated: true,
    style: { stroke: "#60a5fa", strokeWidth: 2 },
  }));
}

function serializeNode(node) {
  return {
    id: node.id,
    type: node.data.type,
    position: node.position,
    params: node.data.params || {},
    on_error: node.data.on_error || "skip",
    body: node.data.body || [],
    branches: node.data.branches || {},
  };
}
