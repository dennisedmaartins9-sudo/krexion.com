import { useEffect, useState, useRef } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import { Plus, Play, Trash2, RefreshCw, Copy, Square, Clock, ChevronDown, Check, RotateCcw, Globe, AlertTriangle, CheckCircle, Shield } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { Checkbox } from "../components/ui/checkbox";
import MyProxyProvidersCard from "../components/MyProxyProvidersCard";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Fallback copy function that works over HTTP (not just HTTPS)
const copyToClipboard = async (text) => {
  // Try modern clipboard API first
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.log("Clipboard API failed, trying fallback");
    }
  }
  
  // Fallback for HTTP or older browsers
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.left = "-999999px";
  textArea.style.top = "-999999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  
  try {
    document.execCommand('copy');
    textArea.remove();
    return true;
  } catch (err) {
    console.error("Fallback copy failed:", err);
    textArea.remove();
    return false;
  }
};

export default function ProxiesPage() {
  const [proxies, setProxies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [proxyText, setProxyText] = useState("");
  const [proxyType, setProxyType] = useState("http");
  const [testing, setTesting] = useState({});
  const [activeFilters, setActiveFilters] = useState([]); // Support multiple filters
  const [deleteCategories, setDeleteCategories] = useState([]); // Categories to delete
  const [deletePopoverOpen, setDeletePopoverOpen] = useState(false);
  const [selectedProxies, setSelectedProxies] = useState([]);
  const [isBulkTesting, setIsBulkTesting] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const stopTestingRef = useRef(false);
  
  // Bulk test live progress (polled from backend)
  const [progress, setProgress] = useState({
    status: "idle",
    total: 0,
    checked: 0,
    parallel_active: 0,
    alive: 0,
    dead: 0,
    duplicate: 0,
    elapsed_seconds: 0,
    percent: 0,
  });
  const progressPollRef = useRef(null);
  
  // Bulk test results summary state
  const [bulkTestResults, setBulkTestResults] = useState(null);
  const [showBulkTestSummary, setShowBulkTestSummary] = useState(false);

  const [ipCheckOpen, setIpCheckOpen] = useState(false);
  const [ipCheckText, setIpCheckText] = useState("");
  const [ipCheckLoading, setIpCheckLoading] = useState(false);
  const [ipCheckResults, setIpCheckResults] = useState(null);

  // Poll live progress while a bulk test is running
  useEffect(() => {
    if (isBulkTesting) {
      const poll = async () => {
        try {
          const res = await axios.get(`${API}/proxies/test-progress`, {
            headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
          });
          setProgress(res.data);
        } catch (err) {
          // silent — keep last known state
        }
      };
      poll();
      progressPollRef.current = setInterval(poll, 500);
    } else {
      if (progressPollRef.current) {
        clearInterval(progressPollRef.current);
        progressPollRef.current = null;
      }
    }
    return () => {
      if (progressPollRef.current) {
        clearInterval(progressPollRef.current);
        progressPollRef.current = null;
      }
    };
  }, [isBulkTesting]);
  
  // Generate bulk test summary - using only proxy IP data (no user-real-IP dependency)
  const generateBulkTestSummary = (testedProxies) => {
    const allIps = new Map(); // IP -> { count, proxies, isUnique }
    
    testedProxies.forEach(proxy => {
      // Add IPv4
      if (proxy.detected_ipv4 || proxy.detected_ip) {
        const ipv4 = proxy.detected_ipv4 || proxy.detected_ip;
        if (!allIps.has(ipv4)) {
          const proxyIsDuplicate = proxy.is_duplicate_click || proxy.is_duplicate;
          allIps.set(ipv4, { 
            type: 'IPv4 (Proxy Exit)', 
            count: 0, 
            proxies: [], 
            isDuplicate: proxyIsDuplicate,
            matchedIp: proxy.duplicate_matched_ip
          });
        }
        const entry = allIps.get(ipv4);
        entry.count++;
        entry.proxies.push(proxy.proxy_string);
      }
      
      // Add IPv6 from proxy (if detected)
      if (proxy.detected_ipv6) {
        if (!allIps.has(proxy.detected_ipv6)) {
          const proxyIsDuplicate = proxy.is_duplicate_click || proxy.is_duplicate;
          allIps.set(proxy.detected_ipv6, { 
            type: 'IPv6 (Proxy Exit)', 
            count: 0, 
            proxies: [], 
            isDuplicate: proxyIsDuplicate,
            matchedIp: proxy.duplicate_matched_ip
          });
        }
        const entry = allIps.get(proxy.detected_ipv6);
        entry.count++;
        entry.proxies.push(proxy.proxy_string);
      }
    });
    
    // Convert to array and separate unique vs duplicate
    const uniqueIps = [];
    const duplicateIps = [];
    
    allIps.forEach((value, ip) => {
      const ipData = { ip, ...value };
      if (value.isDuplicate) {
        duplicateIps.push(ipData);
      } else {
        uniqueIps.push(ipData);
      }
    });
    
    return {
      totalProxies: testedProxies.length,
      aliveProxies: testedProxies.filter(p => p.status === 'alive').length,
      deadProxies: testedProxies.filter(p => p.status === 'dead').length,
      uniqueIps,
      duplicateIps,
      totalUniqueIps: uniqueIps.length,
      totalDuplicateIps: duplicateIps.length
    };
  };

  useEffect(() => {
    fetchProxies();
  }, []);

  // Apply multiple filters to proxies
  const getFilteredProxies = () => {
    if (activeFilters.length === 0) return proxies;
    
    return proxies.filter(proxy => {
      // Apply each active filter as AND condition
      return activeFilters.every(filter => {
        switch (filter) {
          case "unique":
            return !proxy.is_duplicate;
          case "duplicate":
            return proxy.is_duplicate;
          case "alive":
            return proxy.status === "alive";
          case "dead":
            return proxy.status === "dead";
          case "pending":
            return proxy.status === "pending";
          case "vpn":
            return proxy.is_vpn;
          case "clean":
            return !proxy.is_vpn && proxy.status === "alive";
          default:
            return true;
        }
      });
    });
  };

  const filteredProxies = getFilteredProxies();

  const toggleFilter = (filterName) => {
    setActiveFilters(prev => {
      if (prev.includes(filterName)) {
        return prev.filter(f => f !== filterName);
      } else {
        // Remove conflicting filters
        let newFilters = [...prev, filterName];
        // Remove conflicting filters
        if (filterName === "unique") newFilters = newFilters.filter(f => f !== "duplicate");
        if (filterName === "duplicate") newFilters = newFilters.filter(f => f !== "unique");
        if (filterName === "alive") newFilters = newFilters.filter(f => f !== "dead" && f !== "pending");
        if (filterName === "dead") newFilters = newFilters.filter(f => f !== "alive" && f !== "pending");
        if (filterName === "pending") newFilters = newFilters.filter(f => f !== "alive" && f !== "dead");
        if (filterName === "vpn") newFilters = newFilters.filter(f => f !== "clean");
        if (filterName === "clean") newFilters = newFilters.filter(f => f !== "vpn");
        return newFilters;
      }
    });
  };

  const clearFilters = () => {
    setActiveFilters([]);
  };

  const fetchProxies = async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem("token");
      if (!token) {
        toast.error("Please login to view proxies");
        setLoading(false);
        return;
      }
      const response = await axios.get(`${API}/proxies?filter=all`, {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 30000, // 30 second timeout
      });
      setProxies(response.data || []);
      setSelectedProxies([]);
    } catch (error) {
      console.error("Proxy fetch error:", error);
      if (error.code === 'ECONNABORTED') {
        toast.error("Request timed out - please try again");
      } else if (error.response?.status === 403) {
        toast.error("You don't have permission to view proxies");
      } else if (error.response?.status === 401) {
        toast.error("Session expired - please login again");
      } else {
        toast.error("Failed to fetch proxies");
      }
      setProxies([]);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    
    const proxyList = proxyText
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);

    if (proxyList.length === 0) {
      toast.error("Please enter at least one proxy");
      return;
    }

    try {
      const token = localStorage.getItem("token");
      const response = await axios.post(
        `${API}/proxies/upload`,
        { proxy_list: proxyList, proxy_type: proxyType },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      const uploaded = response.data;
      const uniqueCount = uploaded.filter(p => !p.is_duplicate).length;
      const duplicateProxyCount = uploaded.filter(p => p.is_duplicate_proxy).length;
      const duplicateClickCount = uploaded.filter(p => p.is_duplicate_click).length;
      
      let message = `Uploaded: ${uniqueCount} unique`;
      if (duplicateProxyCount > 0) {
        message += `, ${duplicateProxyCount} duplicate proxies`;
      }
      if (duplicateClickCount > 0) {
        message += `, ${duplicateClickCount} match click IPs`;
      }
      
      toast.success(message);
      setDialogOpen(false);
      setProxyText("");
      fetchProxies();
    } catch (error) {
      console.error("Proxy upload error:", error.response?.data || error.message);
      toast.error(error.response?.data?.detail || "Failed to upload proxies");
    }
  };

  const handleIpQualityCheck = async (e) => {
    e.preventDefault();
    const lines = ipCheckText
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
    if (lines.length === 0) {
      toast.error("Kam az kam aik IP likhein");
      return;
    }
    setIpCheckLoading(true);
    setIpCheckResults(null);
    try {
      const token = localStorage.getItem("token");
      const response = await axios.post(
        `${API}/proxies/check-ip`,
        { ips: lines },
        { headers: { Authorization: `Bearer ${token}` }, timeout: 120000 }
      );
      setIpCheckResults(response.data);
      const { total, clean_count, risky_count, invalid = [] } = response.data;
      let msg = `Checked ${total} IP — ${clean_count} clean, ${risky_count} risky`;
      if (invalid.length) msg += ` (${invalid.length} invalid skipped)`;
      toast.success(msg);
    } catch (error) {
      const detail = error.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "IP quality check failed");
    } finally {
      setIpCheckLoading(false);
    }
  };

  const getIpRiskBadgeClass = (risk) => {
    const r = (risk || "").toLowerCase();
    if (r === "high" || r === "very high") return "bg-[#EF4444] text-white";
    if (r === "medium") return "bg-[#F59E0B] text-black";
    if (r === "low") return "bg-[#22C55E] text-black";
    return "bg-zinc-700 text-zinc-200";
  };

  const handleTest = async (proxyId) => {
    setTesting({ ...testing, [proxyId]: true });
    try {
      const token = localStorage.getItem("token");
      const response = await axios.post(
        `${API}/proxies/${proxyId}/test?skip_vpn=false`,
        {},
        { 
          headers: { Authorization: `Bearer ${token}` },
          timeout: 15000  // 15 second timeout
        }
      );
      
      if (response.data.status === "alive") {
        const detectedIp = response.data.detected_ip;
        const allDetectedIps = response.data.all_detected_ips || [];
        const duplicateMatchedIp = response.data.duplicate_matched_ip;
        
        // Show all detected IPs if more than one
        const ipInfo = allDetectedIps.length > 1 
          ? `IPs: ${allDetectedIps.join(', ')} (Exit: ${detectedIp})`
          : `IP: ${detectedIp}`;
        
        if (response.data.is_vpn) {
          toast.warning(`Proxy is VPN/Proxy! Score: ${response.data.vpn_score || 'N/A'} - ${ipInfo} (${response.data.response_time}s)`);
        } else if (response.data.is_duplicate_click) {
          const matchInfo = duplicateMatchedIp ? ` (Matched: ${duplicateMatchedIp})` : '';
          toast.warning(`Proxy alive but IP found in database!${matchInfo} Exit IP: ${detectedIp} (${response.data.response_time}s)`);
        } else {
          toast.success(`Proxy is alive & clean! Exit IP: ${detectedIp} (${response.data.response_time}s)`);
        }
      } else {
        toast.error(`Proxy is dead: ${response.data.error}`);
      }
      
      fetchProxies();
    } catch (error) {
      toast.error("Failed to test proxy");
    } finally {
      setTesting({ ...testing, [proxyId]: false });
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this proxy?")) return;

    try {
      const token = localStorage.getItem("token");
      await axios.delete(`${API}/proxies/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success("Proxy deleted successfully");
      fetchProxies();
    } catch (error) {
      toast.error("Failed to delete proxy");
    }
  };

  const handleBulkDelete = async () => {
    if (selectedProxies.length === 0) {
      toast.error("No proxies selected");
      return;
    }

    if (!window.confirm(`Are you sure you want to delete ${selectedProxies.length} proxies?`)) return;

    try {
      const token = localStorage.getItem("token");
      await axios.post(
        `${API}/proxies/bulk-delete`,
        selectedProxies,
        { headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } }
      );
      toast.success(`${selectedProxies.length} proxies deleted successfully`);
      fetchProxies();
    } catch (error) {
      toast.error("Failed to delete proxies");
    }
  };

  const handleDeleteByCategory = async (category) => {
    let proxyIds = [];
    let categoryLabel = "";
    
    switch (category) {
      case "duplicate":
        proxyIds = proxies.filter(p => p.is_duplicate).map(p => p.id);
        categoryLabel = "duplicate";
        break;
      case "vpn":
        proxyIds = proxies.filter(p => p.is_vpn).map(p => p.id);
        categoryLabel = "VPN";
        break;
      case "dead":
        proxyIds = proxies.filter(p => p.status === "dead").map(p => p.id);
        categoryLabel = "dead";
        break;
      case "pending":
        proxyIds = proxies.filter(p => p.status === "pending").map(p => p.id);
        categoryLabel = "pending";
        break;
      case "in_clicks":
        proxyIds = proxies.filter(p => p.is_duplicate_click).map(p => p.id);
        categoryLabel = "in-clicks";
        break;
      default:
        return;
    }

    if (proxyIds.length === 0) {
      toast.info(`No ${categoryLabel} proxies to delete`);
      return;
    }

    if (!window.confirm(`Are you sure you want to delete all ${proxyIds.length} ${categoryLabel} proxies?`)) return;

    try {
      const token = localStorage.getItem("token");
      await axios.post(
        `${API}/proxies/bulk-delete`,
        proxyIds,
        { headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } }
      );
      toast.success(`${proxyIds.length} ${categoryLabel} proxies deleted successfully`);
      fetchProxies();
    } catch (error) {
      toast.error("Failed to delete proxies");
    }
  };

  const toggleDeleteCategory = (category) => {
    setDeleteCategories(prev => 
      prev.includes(category) 
        ? prev.filter(c => c !== category) 
        : [...prev, category]
    );
  };

  const handleDeleteCheckedCategories = async () => {
    if (deleteCategories.length === 0) {
      toast.error("Please select at least one category to delete");
      return;
    }

    // Collect all proxy IDs matching selected categories
    let proxyIdsToDelete = new Set();
    let categoryLabels = [];

    deleteCategories.forEach(category => {
      switch (category) {
        case "duplicate":
          proxies.filter(p => p.is_duplicate).forEach(p => proxyIdsToDelete.add(p.id));
          categoryLabels.push("Duplicates");
          break;
        case "vpn":
          proxies.filter(p => p.is_vpn).forEach(p => proxyIdsToDelete.add(p.id));
          categoryLabels.push("VPN");
          break;
        case "dead":
          proxies.filter(p => p.status === "dead").forEach(p => proxyIdsToDelete.add(p.id));
          categoryLabels.push("Dead");
          break;
        case "pending":
          proxies.filter(p => p.status === "pending").forEach(p => proxyIdsToDelete.add(p.id));
          categoryLabels.push("Pending");
          break;
        case "in_clicks":
          proxies.filter(p => p.is_duplicate_click).forEach(p => proxyIdsToDelete.add(p.id));
          categoryLabels.push("In Clicks");
          break;
        default:
          break;
      }
    });

    const idsArray = Array.from(proxyIdsToDelete);
    
    if (idsArray.length === 0) {
      toast.info("No proxies match the selected categories");
      return;
    }

    if (!window.confirm(`Delete ${idsArray.length} proxies from categories: ${categoryLabels.join(", ")}?`)) return;

    try {
      const token = localStorage.getItem("token");
      await axios.post(
        `${API}/proxies/bulk-delete`,
        idsArray,
        { headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } }
      );
      toast.success(`${idsArray.length} proxies deleted (${categoryLabels.join(", ")})`);
      setDeleteCategories([]);
      setDeletePopoverOpen(false);
      fetchProxies();
    } catch (error) {
      toast.error("Failed to delete proxies");
    }
  };

  const toggleSelectProxy = (id) => {
    setSelectedProxies((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  };

  const toggleSelectAll = () => {
    if (selectedProxies.length === filteredProxies.length && filteredProxies.length > 0) {
      setSelectedProxies([]);
    } else {
      setSelectedProxies(filteredProxies.map((p) => p.id));
    }
  };

  const refreshDuplicateStatus = async () => {
    setIsRefreshing(true);
    try {
      const token = localStorage.getItem("token");
      const response = await axios.post(
        `${API}/proxies/refresh-status`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const data = response.data;
      if (data.new_duplicates_found > 0) {
        toast.warning(`Found ${data.new_duplicates_found} new duplicate IPs (already used in clicks)`);
      } else if (data.updated > 0) {
        toast.success(`Updated ${data.updated} proxy statuses`);
      } else {
        toast.success("All proxy statuses are up to date");
      }
      fetchProxies();
    } catch (error) {
      toast.error("Failed to refresh status");
    } finally {
      setIsRefreshing(false);
    }
  };

  const testAllProxies = async () => {
    stopTestingRef.current = false;
    setIsBulkTesting(true);
    
    const proxyIds = proxies.map(p => p.id);
    toast.info(`Testing ${proxyIds.length} proxies...`);
    
    try {
      const response = await axios.post(
        `${API}/proxies/bulk-test`,
        { 
          proxy_ids: proxyIds,
          skip_vpn_check: false,
          batch_size: 100,  // Increased for faster testing
          timeout: 3  // Reduced for faster response
        },
        { 
          headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
          timeout: 300000  // 5 minute timeout
        }
      );
      
      const result = response.data;
      toast.success(
        `Done! Alive: ${result.alive}, Dead: ${result.dead}, Duplicate: ${result.duplicate}, VPN: ${result.vpn}. Click "View Last Summary" to see details.`,
        { duration: 6000 }
      );
      
      // Fetch updated proxies and prepare summary (but don't auto-open dialog)
      const proxiesResponse = await axios.get(`${API}/proxies`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
      });
      const updatedProxies = proxiesResponse.data;
      setProxies(updatedProxies);
      
      // Generate bulk test summary — store it, user can open via button
      const testedProxies = updatedProxies.filter(p => p.status === 'alive' || p.status === 'dead');
      const summary = generateBulkTestSummary(testedProxies);
      setBulkTestResults(summary);
      // Do NOT auto-open dialog — its backdrop blocks delete/test buttons
      // setShowBulkTestSummary(true);
      
    } catch (error) {
      console.error("Bulk test error:", error);
      toast.error("Bulk test failed: " + (error.response?.data?.detail || error.message));
    } finally {
      setIsBulkTesting(false);
    }
  };

  const testPendingProxies = async () => {
    const pendingProxies = proxies.filter(p => p.status === "pending");
    if (pendingProxies.length === 0) {
      toast.info("No pending proxies to test");
      return;
    }
    
    stopTestingRef.current = false;
    setIsBulkTesting(true);
    
    const proxyIds = pendingProxies.map(p => p.id);
    toast.info(`Testing ${proxyIds.length} pending proxies...`);
    
    try {
      const response = await axios.post(
        `${API}/proxies/bulk-test`,
        { 
          proxy_ids: proxyIds,
          skip_vpn_check: false,
          batch_size: 100,
          timeout: 3
        },
        { 
          headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
          timeout: 300000
        }
      );
      
      const result = response.data;
      toast.success(
        `Pending test complete! Alive: ${result.alive}, Dead: ${result.dead}, Duplicate: ${result.duplicate}`
      );
      
      await fetchProxies();
    } catch (error) {
      toast.error("Bulk test failed");
    } finally {
      setIsBulkTesting(false);
    }
  };

  const stopTesting = () => {
    stopTestingRef.current = true;
    toast.info("Stopping tests...");
  };

  const copyUniqueProxies = () => {
    const uniqueProxies = proxies
      .filter((p) => !p.is_duplicate && p.status === "alive")
      .map((p) => p.proxy_string)
      .join("\n");

    if (uniqueProxies) {
      copyToClipboard(uniqueProxies);
      toast.success(`Copied ${uniqueProxies.split('\n').length} unique alive proxies (not in clicks database)`);
    } else {
      toast.error("No unique alive proxies to copy");
    }
  };

  const copyAllUniqueProxies = () => {
    const uniqueProxies = proxies
      .filter((p) => !p.is_duplicate)
      .map((p) => p.proxy_string)
      .join("\n");

    if (uniqueProxies) {
      copyToClipboard(uniqueProxies);
      toast.success(`Copied ${uniqueProxies.split('\n').length} unique proxies (not in clicks or proxy list)`);
    } else {
      toast.error("No unique proxies to copy");
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case "alive":
        return "bg-[#22C55E]";
      case "dead":
        return "bg-[#EF4444]";
      default:
        return "bg-[#A1A1AA]";
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#3B82F6]"></div>
        <div className="text-muted-foreground">Loading proxies...</div>
      </div>
    );
  }

  const aliveCount = proxies.filter((p) => p.status === "alive").length;
  const deadCount = proxies.filter((p) => p.status === "dead").length;
  const pendingCount = proxies.filter((p) => p.status === "pending").length;
  const uniqueCount = proxies.filter((p) => !p.is_duplicate).length;
  const duplicateCount = proxies.filter((p) => p.is_duplicate).length;
  const vpnCount = proxies.filter((p) => p.is_vpn).length;
  const cleanCount = proxies.filter((p) => p.status === "alive" && !p.is_vpn).length;

  return (
    <div className="space-y-6" data-testid="proxies-page">
      {/* v2.6.1 — Customer's own proxy providers (Settings › Proxy Providers) */}
      {/* ProxyJet-specific card removed — providers now handle every proxy source. */}
      <MyProxyProvidersCard />

      {/* Bulk Test Summary Dialog */}
      <Dialog open={showBulkTestSummary} onOpenChange={setShowBulkTestSummary}>
        <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <RefreshCw className="text-[#3B82F6]" size={20} />
              Bulk Test Results Summary
            </DialogTitle>
            <DialogDescription>
              All detected IPs from proxy testing - showing unique vs duplicate status
            </DialogDescription>
          </DialogHeader>
          
          {bulkTestResults && (
            <div className="space-y-4">
              {/* Stats Overview */}
              <div className="grid grid-cols-4 gap-3">
                <div className="p-3 bg-[var(--brand-card)] rounded-lg text-center">
                  <p className="text-2xl font-bold text-white">{bulkTestResults.totalProxies}</p>
                  <p className="text-xs text-[#A1A1AA]">Total Tested</p>
                </div>
                <div className="p-3 bg-[#22C55E]/10 rounded-lg text-center">
                  <p className="text-2xl font-bold text-[#22C55E]">{bulkTestResults.aliveProxies}</p>
                  <p className="text-xs text-[#A1A1AA]">Alive</p>
                </div>
                <div className="p-3 bg-[#3B82F6]/10 rounded-lg text-center">
                  <p className="text-2xl font-bold text-[#3B82F6]">{bulkTestResults.uniqueIps.length}</p>
                  <p className="text-xs text-[#A1A1AA]">Unique Proxy IPs</p>
                </div>
                <div className="p-3 bg-[#EF4444]/10 rounded-lg text-center">
                  <p className="text-2xl font-bold text-[#EF4444]">{bulkTestResults.duplicateIps.length}</p>
                  <p className="text-xs text-[#A1A1AA]">Duplicate Proxy IPs</p>
                </div>
              </div>
              
              {/* Unique IPs Section */}
              {bulkTestResults.uniqueIps.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-[#22C55E] flex items-center gap-2">
                      <CheckCircle size={16} />
                      Unique Proxy IPs ({bulkTestResults.uniqueIps.length}) - Safe to use!
                    </h4>
                    <Button
                      variant="outline"
                      size="sm"
                      className="border-[#22C55E] text-[#22C55E] h-7 text-xs"
                      onClick={() => {
                        const uniqueProxyStrings = bulkTestResults.uniqueIps
                          .flatMap(ip => ip.proxies)
                          .filter((v, i, a) => a.indexOf(v) === i)
                          .join("\n");
                        copyToClipboard(uniqueProxyStrings);
                        toast.success(`Copied proxies with unique IPs to clipboard`);
                      }}
                    >
                      <Copy size={12} className="mr-1" />
                      Copy All Unique
                    </Button>
                  </div>
                  <div className="max-h-40 overflow-y-auto space-y-1 p-2 bg-[#22C55E]/5 rounded-lg">
                    {bulkTestResults.uniqueIps.map((ipData, i) => (
                      <div key={i} className="flex items-center justify-between p-2 bg-[var(--brand-card)] rounded text-xs">
                        <div className="flex items-center gap-2">
                          <Badge className="bg-[#22C55E]/20 text-[#22C55E] text-[10px]">{ipData.type}</Badge>
                          <span className="font-mono text-white">{(ipData.ip || '').length > 30 ? (ipData.ip || '').substring(0, 30) + '...' : (ipData.ip || '')}</span>
                        </div>
                        <span className="text-[#A1A1AA]">{ipData.count} proxy(s)</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Duplicate IPs Section */}
              {bulkTestResults.duplicateIps.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-medium text-[#EF4444] flex items-center gap-2">
                    <AlertTriangle size={16} />
                    Duplicate Proxy IPs ({bulkTestResults.duplicateIps.length}) - Already in database
                  </h4>
                  <div className="max-h-40 overflow-y-auto space-y-1 p-2 bg-[#EF4444]/5 rounded-lg">
                    {bulkTestResults.duplicateIps.map((ipData, i) => (
                      <div key={i} className="flex items-center justify-between p-2 bg-[var(--brand-card)] rounded text-xs">
                        <div className="flex items-center gap-2">
                          <Badge className="bg-[#EF4444]/20 text-[#EF4444] text-[10px]">{ipData.type}</Badge>
                          <span className="font-mono text-white">{(ipData.ip || '').length > 30 ? (ipData.ip || '').substring(0, 30) + '...' : (ipData.ip || '')}</span>
                        </div>
                        <span className="text-[#A1A1AA]">{ipData.count} proxy(s)</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* No IPs detected */}
              {bulkTestResults.uniqueIps.length === 0 && bulkTestResults.duplicateIps.length === 0 && (
                <div className="p-4 bg-[var(--brand-card)] rounded-lg text-center">
                  <p className="text-[#A1A1AA]">No IPs detected. Make sure proxies are alive and working.</p>
                </div>
              )}
              
              {/* Instructions */}
              <div className="text-xs text-[#A1A1AA] p-3 bg-[var(--brand-card)] rounded-lg">
                <p className="font-medium text-white mb-1">Important:</p>
                <ul className="list-disc list-inside space-y-1">
                  <li>Proxy IPs are checked against database</li>
                  <li><span className="text-[#F59E0B]">Your real IPv6 LEAKS through proxies!</span></li>
                  <li>If your real IP is in database, links won't work even with unique proxy</li>
                  <li>Clear your IP from Clicks page or disable IPv6 first</li>
                </ul>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Proxy Management</h2>
        <div className="flex gap-2 flex-wrap items-center">
          {selectedProxies.length > 0 && (
            <>
              <span className="text-sm text-[#3B82F6] font-medium px-3 py-1 bg-[#3B82F6]/10 rounded-md" data-testid="selected-count">
                {selectedProxies.length} selected
              </span>
              <Button 
                variant="outline" 
                onClick={() => {
                  const selectedProxyStrings = proxies
                    .filter(p => selectedProxies.includes(p.id))
                    .map(p => p.proxy_string)
                    .join("\n");
                  copyToClipboard(selectedProxyStrings);
                  toast.success(`Copied ${selectedProxies.length} proxies to clipboard`);
                }} 
                data-testid="copy-selected-button"
                className="border-[#3B82F6] text-[#3B82F6]"
              >
                <Copy size={16} className="mr-2" />
                Copy Selected
              </Button>
              <Button variant="destructive" onClick={handleBulkDelete} data-testid="bulk-delete-button">
                <Trash2 size={16} className="mr-2" />
                Delete Selected
              </Button>
            </>
          )}
          {proxies.length > 0 && (
            <>
              <Popover open={deletePopoverOpen} onOpenChange={setDeletePopoverOpen}>
                <PopoverTrigger asChild>
                  <Button variant="destructive" data-testid="delete-by-category-button">
                    <Trash2 size={16} className="mr-2" />
                    Delete By
                    <ChevronDown size={16} className="ml-2" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-64 bg-[var(--brand-card)] border-[var(--brand-border)] p-3" align="end">
                  <div className="space-y-3">
                    <p className="text-sm font-medium text-white">Select categories to delete:</p>
                    
                    <div className="space-y-2">
                      <label className="flex items-center gap-3 cursor-pointer hover:bg-[var(--brand-card)] p-2 rounded-md">
                        <Checkbox 
                          checked={deleteCategories.includes("duplicate")}
                          onCheckedChange={() => toggleDeleteCategory("duplicate")}
                          data-testid="checkbox-duplicate"
                        />
                        <span className="text-[#A1A1AA] text-sm">Duplicates ({duplicateCount})</span>
                      </label>
                      
                      <label className="flex items-center gap-3 cursor-pointer hover:bg-[var(--brand-card)] p-2 rounded-md">
                        <Checkbox 
                          checked={deleteCategories.includes("vpn")}
                          onCheckedChange={() => toggleDeleteCategory("vpn")}
                          data-testid="checkbox-vpn"
                        />
                        <span className="text-[#F59E0B] text-sm">VPN ({vpnCount})</span>
                      </label>
                      
                      <label className="flex items-center gap-3 cursor-pointer hover:bg-[var(--brand-card)] p-2 rounded-md">
                        <Checkbox 
                          checked={deleteCategories.includes("dead")}
                          onCheckedChange={() => toggleDeleteCategory("dead")}
                          data-testid="checkbox-dead"
                        />
                        <span className="text-[#EF4444] text-sm">Dead ({deadCount})</span>
                      </label>
                      
                      <label className="flex items-center gap-3 cursor-pointer hover:bg-[var(--brand-card)] p-2 rounded-md">
                        <Checkbox 
                          checked={deleteCategories.includes("pending")}
                          onCheckedChange={() => toggleDeleteCategory("pending")}
                          data-testid="checkbox-pending"
                        />
                        <span className="text-[#71717A] text-sm">Pending ({pendingCount})</span>
                      </label>
                      
                      <label className="flex items-center gap-3 cursor-pointer hover:bg-[var(--brand-card)] p-2 rounded-md">
                        <Checkbox 
                          checked={deleteCategories.includes("in_clicks")}
                          onCheckedChange={() => toggleDeleteCategory("in_clicks")}
                          data-testid="checkbox-in-clicks"
                        />
                        <span className="text-[#EF4444] text-sm">In Clicks ({proxies.filter(p => p.is_duplicate_click).length})</span>
                      </label>
                    </div>
                    
                    <div className="pt-2 border-t border-[var(--brand-border)]">
                      <Button 
                        variant="destructive" 
                        className="w-full"
                        onClick={handleDeleteCheckedCategories}
                        disabled={deleteCategories.length === 0}
                        data-testid="delete-checked-button"
                      >
                        <Trash2 size={14} className="mr-2" />
                        Delete Checked ({deleteCategories.length})
                      </Button>
                    </div>
                  </div>
                </PopoverContent>
              </Popover>
              <Button variant="outline" onClick={copyAllUniqueProxies} data-testid="copy-all-unique-button">
                <Copy size={16} className="mr-2" />
                Copy All Unique
              </Button>
              <Button variant="outline" onClick={copyUniqueProxies} data-testid="copy-unique-alive-button">
                <Copy size={16} className="mr-2" />
                Copy Unique Alive
              </Button>
              {bulkTestResults && !isBulkTesting && (
                <Button
                  variant="outline"
                  onClick={() => setShowBulkTestSummary(true)}
                  className="border-[#3B82F6] text-[#3B82F6] hover:bg-[#3B82F6]/10"
                  data-testid="view-last-summary-button"
                >
                  <RefreshCw size={16} className="mr-2" />
                  View Last Summary
                </Button>
              )}
              {isBulkTesting ? (
                <Button variant="destructive" onClick={stopTesting} data-testid="stop-testing-button">
                  <Square size={16} className="mr-2" />
                  Stop Testing
                </Button>
              ) : (
                <>
                  <Button 
                    variant="outline" 
                    onClick={refreshDuplicateStatus} 
                    disabled={isRefreshing}
                    data-testid="refresh-status-button"
                    className="border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/10"
                  >
                    <RotateCcw size={16} className={`mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
                    {isRefreshing ? "Checking..." : "Refresh Duplicates"}
                  </Button>
                  <Button variant="outline" onClick={testPendingProxies} data-testid="test-pending-button">
                    <Clock size={16} className="mr-2" />
                    Test Pending ({pendingCount})
                  </Button>
                  <Button variant="outline" onClick={testAllProxies} data-testid="test-all-proxies-button">
                    <RefreshCw size={16} className="mr-2" />
                    Test All
                  </Button>
                </>
              )}
            </>
          )}
          <Dialog open={ipCheckOpen} onOpenChange={setIpCheckOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" data-testid="check-ip-quality-button" className="border-[#06B6D4] text-[#06B6D4] hover:bg-[#06B6D4]/10">
                <Shield size={16} className="mr-2" />
                Check IP Quality
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-4xl max-h-[90vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle>Check IP Quality</DialogTitle>
                <DialogDescription className="space-y-1">
                  <span className="block">Sirf IP paste karein — proxy string ki zaroorat nahi. Scamalytics, IPQualityScore, IPHub ya ProxyCheck se fraud score aur geo details milengi.</span>
                  <span className="block text-[11px] text-zinc-500">Ek line par aik IP (IPv4 ya IPv6). Max 50 IPs per check.</span>
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={handleIpQualityCheck} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="ip_check_list">IP List</Label>
                  <Textarea
                    id="ip_check_list"
                    data-testid="ip-check-textarea"
                    placeholder={"203.0.113.45\n198.51.100.22\n2001:db8::1"}
                    value={ipCheckText}
                    onChange={(e) => setIpCheckText(e.target.value)}
                    className="bg-[var(--brand-card)] border-[var(--brand-border)] font-mono text-xs min-h-[140px]"
                    required
                  />
                </div>
                <Button type="submit" data-testid="submit-ip-check-button" className="w-full" disabled={ipCheckLoading}>
                  <Shield size={16} className={`mr-2 ${ipCheckLoading ? "animate-pulse" : ""}`} />
                  {ipCheckLoading ? "Checking..." : "Check IP Quality"}
                </Button>
              </form>
              {ipCheckResults && (
                <div className="space-y-3 pt-2 border-t border-[var(--brand-border)]">
                  <div className="flex flex-wrap gap-3 text-sm">
                    <span className="text-zinc-400">Total: <span className="text-white font-mono">{ipCheckResults.total}</span></span>
                    <span className="text-[#22C55E]">Clean: {ipCheckResults.clean_count}</span>
                    <span className="text-[#F59E0B]">Risky: {ipCheckResults.risky_count}</span>
                    {ipCheckResults.truncated && (
                      <span className="text-[#EF4444] text-xs">(first 50 only)</span>
                    )}
                  </div>
                  {ipCheckResults.invalid?.length > 0 && (
                    <p className="text-xs text-[#EF4444]">
                      Invalid skipped: {ipCheckResults.invalid.join(", ")}
                    </p>
                  )}
                  <div className="rounded-md border border-[var(--brand-border)] overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>IP</TableHead>
                          <TableHead>Fraud</TableHead>
                          <TableHead>Quality</TableHead>
                          <TableHead>Risk</TableHead>
                          <TableHead>Country</TableHead>
                          <TableHead>Flags</TableHead>
                          <TableHead>Provider</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {(ipCheckResults.results || []).map((row) => (
                          <TableRow key={row.ip}>
                            <TableCell className="font-mono text-xs">{row.ip}</TableCell>
                            <TableCell>
                              {row.error ? (
                                <span className="text-[#EF4444] text-xs">Error</span>
                              ) : (
                                <span className="font-mono text-xs">{row.fraud_score ?? 0}</span>
                              )}
                            </TableCell>
                            <TableCell className="font-mono text-xs text-[#06B6D4]">{row.quality_score ?? "-"}</TableCell>
                            <TableCell>
                              <Badge className={`text-xs ${getIpRiskBadgeClass(row.risk)}`}>{row.risk || "-"}</Badge>
                            </TableCell>
                            <TableCell className="text-xs">{row.country || "-"}</TableCell>
                            <TableCell>
                              <div className="flex flex-wrap gap-1">
                                {row.is_vpn && <Badge className="bg-[#F59E0B] text-black text-[10px]">VPN</Badge>}
                                {row.is_proxy && <Badge className="bg-[#F59E0B] text-black text-[10px]">Proxy</Badge>}
                                {row.is_hosting && <Badge variant="outline" className="text-[10px]">Hosting</Badge>}
                                {row.is_datacenter && <Badge variant="outline" className="text-[10px]">DC</Badge>}
                                {row.is_tor && <Badge className="bg-[#EF4444] text-white text-[10px]">Tor</Badge>}
                                {!row.is_vpn && !row.is_proxy && !row.is_hosting && !row.error && (
                                  <Badge variant="outline" className="border-[#22C55E] text-[#22C55E] text-[10px]">Clean</Badge>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="text-[10px] text-zinc-400 max-w-[120px] truncate" title={row.source}>
                              {row.provider || row.source || "-"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}
            </DialogContent>
          </Dialog>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button data-testid="upload-proxies-button">
                <Plus size={16} className="mr-2" />
                Upload Proxies
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)] max-w-2xl">
              <DialogHeader>
                <DialogTitle>Add Proxies — Any Provider</DialogTitle>
                <DialogDescription className="space-y-1">
                  <span className="block">Works with <span className="text-cyan-300">any proxy provider</span> — BrightData, SmartProxy, Oxylabs, IPRoyal, Nimble, Rayobyte, GeoNode, BestGo, DataImpulse, ProxyEmpire, and many more.</span>
                  <span className="block text-[11px] text-zinc-500">Paste one proxy per line. Any of these 5 formats auto-detected:</span>
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={handleUpload} className="space-y-4">
                <div className="p-2.5 rounded-md bg-zinc-950 border border-zinc-800 text-[11px] font-mono text-zinc-400 space-y-0.5">
                  <div><span className="text-cyan-300">1.</span> http://user:pass@host:port   <span className="text-zinc-600"># canonical URL</span></div>
                  <div><span className="text-cyan-300">2.</span> http://host:port:user:pass   <span className="text-zinc-600"># BestGo / GeoNode</span></div>
                  <div><span className="text-cyan-300">3.</span> user:pass@host:port          <span className="text-zinc-600"># bare, no scheme</span></div>
                  <div><span className="text-cyan-300">4.</span> host:port:user:pass          <span className="text-zinc-600"># Krexion shorthand</span></div>
                  <div><span className="text-cyan-300">5.</span> host:port                    <span className="text-zinc-600"># no auth</span></div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="proxy_type">Default Protocol <span className="text-zinc-500 text-[11px]">(used when line has no scheme)</span></Label>
                  <select
                    id="proxy_type"
                    data-testid="proxy-type-select"
                    value={proxyType}
                    onChange={(e) => setProxyType(e.target.value)}
                    className="flex h-9 w-full rounded-md border border-[var(--brand-border)] bg-[var(--brand-card)] px-3 py-1 text-sm text-white"
                  >
                    <option value="http">HTTP</option>
                    <option value="https">HTTPS</option>
                    <option value="socks5">SOCKS5</option>
                    <option value="socks5h">SOCKS5H (remote DNS)</option>
                    <option value="socks4">SOCKS4</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="proxy_list">Proxy List <span className="text-zinc-500 text-[11px]">(one per line, any format above)</span></Label>
                  <Textarea
                    id="proxy_list"
                    data-testid="proxy-list-textarea"
                    placeholder={"http://user1:pass1@gate.smartproxy.com:7000\nhttp://us.rrp.bestgo.work:10000:USER123:pass456\n192.168.1.1:3128:admin:secret\n45.67.89.10:8080"}
                    value={proxyText}
                    onChange={(e) => setProxyText(e.target.value)}
                    className="bg-[var(--brand-card)] border-[var(--brand-border)] font-mono text-xs min-h-[200px]"
                    required
                  />
                </div>
                <div className="text-[10px] text-zinc-500">
                  💡 <span className="text-zinc-400">Tip:</span> Ye page general-purpose proxy pool ke liye hai. Agar aap residential rotating (unique IP per visit) chahte hain, upar wale <span className="text-cyan-300">My Proxy Providers</span> card se apna provider add karein.
                </div>
                <Button type="submit" data-testid="submit-proxies-button" className="w-full">
                  <Plus size={16} className="mr-2" />
                  Add Proxies to Pool
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {proxies.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Total</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono">{proxies.length}</div>
            </CardContent>
          </Card>
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Alive</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-[#22C55E]">{aliveCount}</div>
            </CardContent>
          </Card>
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Dead</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-[#EF4444]">{deadCount}</div>
            </CardContent>
          </Card>
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">VPN/Proxy</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-[#F59E0B]">{vpnCount}</div>
            </CardContent>
          </Card>
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Clean</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-[#3B82F6]">{cleanCount}</div>
            </CardContent>
          </Card>
          <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Duplicates</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-[#A1A1AA]">{duplicateCount}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Live System Processing card (visible during bulk test) ─────────── */}
      {isBulkTesting && (
        <Card
          className="bg-gradient-to-r from-[#1a0b2e] via-[#0f0418] to-[#1a0b2e] border-[#8B5CF6]/40 overflow-hidden"
          data-testid="system-processing-card"
        >
          <CardContent className="p-0">
            {/* Top progress bar */}
            <div className="relative h-2 bg-[#1a0b2e]">
              <div
                className="absolute top-0 left-0 h-full bg-gradient-to-r from-[#8B5CF6] via-[#A78BFA] to-[#C4B5FD] transition-all duration-300 ease-out"
                style={{ width: `${progress.percent}%` }}
                data-testid="progress-bar-fill"
              />
            </div>

            <div className="flex items-center justify-between flex-wrap gap-6 px-6 py-5">
              {/* Left: spinner + label */}
              <div className="flex items-center gap-4 min-w-[280px]">
                <div className="w-14 h-14 rounded-full bg-[#8B5CF6]/15 border border-[#8B5CF6]/40 flex items-center justify-center shrink-0">
                  <RefreshCw className="text-[#A78BFA] animate-spin" size={26} />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-xl font-bold text-white">System Processing</h3>
                    <span
                      className="text-sm font-semibold text-[#A78BFA] bg-[#8B5CF6]/15 px-2 py-0.5 rounded-md border border-[#8B5CF6]/30"
                      data-testid="progress-percent"
                    >
                      {progress.percent}%
                    </span>
                  </div>
                  <p className="text-xs text-[#A1A1AA] mt-0.5">
                    Parallel batch test active across distributed workers
                  </p>
                </div>
              </div>

              {/* Right: stats */}
              <div className="flex items-center gap-10">
                <div className="text-center">
                  <p className="text-[10px] tracking-widest uppercase text-[#71717A] mb-1">
                    Parallel Active
                  </p>
                  <p
                    className="text-3xl font-bold text-white tabular-nums"
                    data-testid="parallel-active"
                  >
                    {progress.parallel_active}
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-[10px] tracking-widest uppercase text-[#71717A] mb-1">
                    Checked
                  </p>
                  <p
                    className="text-3xl font-bold text-white tabular-nums"
                    data-testid="checked-count"
                  >
                    {progress.checked}
                    <span className="text-[#71717A] text-lg font-normal"> / {progress.total}</span>
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-[10px] tracking-widest uppercase text-[#71717A] mb-1">
                    Time Elapsed
                  </p>
                  <p
                    className="text-3xl font-bold text-[#A78BFA] tabular-nums"
                    data-testid="time-elapsed"
                  >
                    {progress.elapsed_seconds}s
                  </p>
                </div>
              </div>
            </div>

            {/* Footer: live result counters */}
            <div className="flex items-center justify-center gap-6 px-6 py-2 bg-[#0f0418]/60 border-t border-[#8B5CF6]/15 text-xs">
              <span className="text-[#A1A1AA]">
                Alive: <span className="text-[#22C55E] font-semibold">{progress.alive}</span>
              </span>
              <span className="text-[#A1A1AA]">
                Dead: <span className="text-[#EF4444] font-semibold">{progress.dead}</span>
              </span>
              <span className="text-[#A1A1AA]">
                Duplicate: <span className="text-[#F59E0B] font-semibold">{progress.duplicate}</span>
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
        <CardHeader>
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <CardTitle>All Proxies</CardTitle>
              <p className="text-sm text-muted-foreground mt-1">
                Showing {filteredProxies.length} of {proxies.length} proxies
                {activeFilters.length > 0 && (
                  <span className="ml-2">
                    (Filters: {activeFilters.join(" + ")})
                  </span>
                )}
              </p>
            </div>
            <div className="flex gap-2 flex-wrap items-center">
              <span className="text-sm text-muted-foreground mr-2">Toggle Filters:</span>
              <Button
                variant={activeFilters.includes("unique") ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter("unique")}
                data-testid="filter-unique"
                className={activeFilters.includes("unique") ? "bg-[#3B82F6]" : "border-[#3B82F6] text-[#3B82F6]"}
              >
                Unique ({proxies.filter(p => !p.is_duplicate).length})
              </Button>
              <Button
                variant={activeFilters.includes("duplicate") ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter("duplicate")}
                data-testid="filter-duplicate"
                className={activeFilters.includes("duplicate") ? "bg-[#A1A1AA]" : "border-[#A1A1AA] text-[#A1A1AA]"}
              >
                Duplicates ({proxies.filter(p => p.is_duplicate).length})
              </Button>
              <Button
                variant={activeFilters.includes("alive") ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter("alive")}
                data-testid="filter-alive"
                className={activeFilters.includes("alive") ? "bg-[#22C55E]" : "border-[#22C55E] text-[#22C55E]"}
              >
                Alive ({aliveCount})
              </Button>
              <Button
                variant={activeFilters.includes("dead") ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter("dead")}
                data-testid="filter-dead"
                className={activeFilters.includes("dead") ? "bg-[#EF4444]" : "border-[#EF4444] text-[#EF4444]"}
              >
                Dead ({deadCount})
              </Button>
              <Button
                variant={activeFilters.includes("pending") ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter("pending")}
                data-testid="filter-pending"
                className={activeFilters.includes("pending") ? "bg-[#71717A]" : "border-[#71717A] text-[#71717A]"}
              >
                Pending ({pendingCount})
              </Button>
              <Button
                variant={activeFilters.includes("vpn") ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter("vpn")}
                data-testid="filter-vpn"
                className={activeFilters.includes("vpn") ? "bg-[#F59E0B]" : "border-[#F59E0B] text-[#F59E0B]"}
              >
                VPN ({vpnCount})
              </Button>
              <Button
                variant={activeFilters.includes("clean") ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter("clean")}
                data-testid="filter-clean"
                className={activeFilters.includes("clean") ? "bg-[#06B6D4]" : "border-[#06B6D4] text-[#06B6D4]"}
              >
                Clean ({cleanCount})
              </Button>
              {activeFilters.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearFilters}
                  data-testid="clear-filters"
                  className="text-[#EF4444]"
                >
                  Clear All
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                  <TableHead className="w-12">
                    <input
                      type="checkbox"
                      checked={filteredProxies.length > 0 && selectedProxies.length === filteredProxies.length}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 cursor-pointer"
                      data-testid="select-all-checkbox"
                    />
                  </TableHead>
                  <TableHead>Proxy</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>VPN</TableHead>
                  <TableHead>Duplicate</TableHead>
                  <TableHead className="text-right">Response Time</TableHead>
                  <TableHead>Detected IPs (v4/v6)</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredProxies.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                      {proxies.length === 0 ? "No proxies uploaded yet. Click \"Upload Proxies\" to get started." : "No proxies match the selected filters."}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredProxies.map((proxy) => (
                    <TableRow key={proxy.id} className="border-[var(--brand-border)]" data-testid={`proxy-row-${proxy.id}`}>
                      <TableCell>
                        <input
                          type="checkbox"
                          checked={selectedProxies.includes(proxy.id)}
                          onChange={() => toggleSelectProxy(proxy.id)}
                          className="w-4 h-4 cursor-pointer"
                          data-testid={`checkbox-${proxy.id}`}
                        />
                      </TableCell>
                      <TableCell className="font-mono text-xs max-w-xs truncate" title={proxy.proxy_string}>
                        <div>
                          <div>{proxy.proxy_string}</div>
                          {proxy.proxy_ip && (
                            <div className="text-[10px] text-muted-foreground mt-1">IP: {proxy.proxy_ip}</div>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="uppercase">
                          {proxy.proxy_type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge className={getStatusColor(proxy.status)}>{proxy.status}</Badge>
                      </TableCell>
                      <TableCell>
                        {proxy.is_vpn ? (
                          <div className="flex flex-col gap-1">
                            <Badge className="bg-[#F59E0B] text-black text-xs">
                              VPN
                            </Badge>
                            {proxy.vpn_score !== undefined && proxy.vpn_score > 0 && (
                              <span className="text-[10px] text-[#F59E0B]">Score: {proxy.vpn_score}</span>
                            )}
                          </div>
                        ) : proxy.is_vpn === false ? (
                          <Badge variant="outline" className="border-[#06B6D4] text-[#06B6D4] text-xs">Clean</Badge>
                        ) : (
                          <span className="text-xs text-[#71717A]">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {proxy.is_duplicate ? (
                          <div className="flex flex-col gap-1">
                            {proxy.is_duplicate_proxy && (
                              <Badge variant="outline" className="border-[#A1A1AA] text-[#A1A1AA] text-xs">
                                Dup Proxy
                              </Badge>
                            )}
                            {proxy.is_duplicate_click && (
                              <Badge variant="outline" className="border-[#EF4444] text-[#EF4444] text-xs">
                                In Clicks
                              </Badge>
                            )}
                          </div>
                        ) : (
                          <Badge variant="outline" className="border-[#3B82F6] text-[#3B82F6]">Unique</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {proxy.response_time ? `${proxy.response_time}s` : "-"}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        <div className="flex flex-col gap-1">
                          {/* IPv4 */}
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] text-[#A1A1AA] w-8">IPv4:</span>
                            <span className={proxy.detected_ipv4 ? "text-white" : "text-[#71717A]"}>
                              {proxy.detected_ipv4 || proxy.detected_ip || "-"}
                            </span>
                          </div>
                          {/* IPv6 */}
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] text-[#A1A1AA] w-8">IPv6:</span>
                            <span className={proxy.detected_ipv6 ? "text-white" : "text-[#71717A]"} title={proxy.detected_ipv6 || ""}>
                              {proxy.detected_ipv6 ? (proxy.detected_ipv6.length > 15 ? proxy.detected_ipv6.substring(0, 15) + "..." : proxy.detected_ipv6) : "-"}
                            </span>
                          </div>
                          {proxy.duplicate_matched_ip && (
                            <span className="text-[10px] text-[#EF4444]">
                              Match: {proxy.duplicate_matched_ip}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleTest(proxy.id)}
                            disabled={testing[proxy.id]}
                            data-testid={`test-proxy-${proxy.id}`}
                          >
                            <Play size={16} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDelete(proxy.id)}
                            data-testid={`delete-proxy-${proxy.id}`}
                            className="text-red-400 hover:text-red-300"
                          >
                            <Trash2 size={16} />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
