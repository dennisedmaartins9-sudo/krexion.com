import { useEffect, useState, useRef } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Checkbox } from "../components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { toast } from "sonner";
import { format, subDays, startOfDay, endOfDay, startOfWeek, startOfMonth } from "date-fns";
import { Trash2, Upload, RefreshCw, Loader2, Wifi, WifiOff, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Download, Calendar, Search, Eye, ChevronDown } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const API = `${BACKEND_URL}/api`;
const WS_URL = BACKEND_URL ? BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://') : "";

export default function ClicksPage() {
  const [clicks, setClicks] = useState([]);
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedClicks, setSelectedClicks] = useState([]);
  
  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const [rowsPerPage, setRowsPerPage] = useState(50);
  
  // Filters
  const [dateFilter, setDateFilter] = useState("all");
  const [linkFilter, setLinkFilter] = useState("all");
  const [ipFilter, setIpFilter] = useState("all");
  
  // Custom Date Range
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [showCustomDateInputs, setShowCustomDateInputs] = useState(false);
  
  // Real-time
  const [realTimeEnabled, setRealTimeEnabled] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);
  
  // IP Import
  const [showIPImportDialog, setShowIPImportDialog] = useState(false);
  const [ipList, setIpList] = useState("");
  const [selectedLinkId, setSelectedLinkId] = useState("none");
  const [ipCountry, setIpCountry] = useState("Unknown");
  const [importingIPs, setImportingIPs] = useState(false);
  
  // Export & Delete
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  
  // Delete by category
  const [deleteByOpen, setDeleteByOpen] = useState(false);
  const [deleteCategories, setDeleteCategories] = useState({
    vpn: false,
    proxy: false,
    duplicate: false
  });

  const getToken = () => localStorage.getItem("token");

  // Get date range based on filter
  const getDateRange = (filter) => {
    const now = new Date();
    switch (filter) {
      case "today":
        return { start: startOfDay(now), end: endOfDay(now) };
      case "yesterday":
        const yesterday = subDays(now, 1);
        return { start: startOfDay(yesterday), end: endOfDay(yesterday) };
      case "week":
        return { start: startOfWeek(now), end: endOfDay(now) };
      case "month":
        return { start: startOfMonth(now), end: endOfDay(now) };
      case "custom":
        if (customStartDate && customEndDate) {
          return { 
            start: new Date(customStartDate + "T00:00:00"), 
            end: new Date(customEndDate + "T23:59:59") 
          };
        }
        return null;
      default:
        return null;
    }
  };

  // Fetch clicks
  const fetchClicks = async (showRefresh = false) => {
    try {
      if (showRefresh) setRefreshing(true);
      let url = `${API}/clicks?`;
      
      const dateRange = getDateRange(dateFilter);
      if (dateRange) {
        url += `start_date=${dateRange.start.toISOString()}&end_date=${dateRange.end.toISOString()}&`;
      }
      
      if (linkFilter !== "all") url += `link_id=${linkFilter}&`;
      
      const response = await axios.get(url, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      setClicks(response.data);
      setSelectedClicks([]);
    } catch (error) {
      toast.error("Failed to load clicks");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Fetch links
  const fetchLinks = async () => {
    try {
      const response = await axios.get(`${API}/links`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      setLinks(response.data);
    } catch (error) {
      console.error("Failed to fetch links");
    }
  };

  useEffect(() => {
    fetchClicks();
    fetchLinks();
    fetchClickStats();
  }, [dateFilter, linkFilter]);

  // Refetch when custom dates change (only if custom filter is active)
  useEffect(() => {
    if (dateFilter === "custom" && customStartDate && customEndDate) {
      fetchClicks();
    }
  }, [customStartDate, customEndDate]);

  // Reset to page 1 when filter changes
  useEffect(() => {
    setCurrentPage(1);
  }, [dateFilter, linkFilter, ipFilter, rowsPerPage]);

  // WebSocket for real-time
  useEffect(() => {
    if (!realTimeEnabled) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setWsConnected(false);
      return;
    }

    const token = getToken();
    if (!token) return;

    try {
      const ws = new WebSocket(`${WS_URL}/ws/clicks/${token}`);
      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => setWsConnected(false);
      ws.onerror = () => setWsConnected(false);
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "new_click") {
            setClicks(prev => [msg.data, ...prev]);
            toast.success("New click!", { duration: 1500 });
          }
        } catch (e) {}
      };
      wsRef.current = ws;
    } catch (e) {}

    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [realTimeEnabled]);

  // Get link name
  const getLinkName = (linkId) => {
    const link = links.find(l => l.id === linkId);
    if (link?.name === "_IP_TRACKING_") return "IP Track";
    return link?.name || link?.short_code || "Unknown";
  };

  // Click stats from API
  const [clickStats, setClickStats] = useState({ count: 0, unique: 0, duplicate: 0, vpn: 0 });
  
  // Fetch click stats
  const fetchClickStats = async () => {
    try {
      let url = `${API}/clicks/count?`;
      // 2026-06 — send the SAME explicit date range we send to /clicks
      // (the list endpoint). Previously this endpoint only got
      // `filter_type=month` which the backend treated as last-30-days,
      // while the list got `start_date=startOfMonth(...)` (calendar
      // month). Result: top-cards showed 8118 but the table showed 0
      // because the two queries were looking at different windows.
      const dateRange = getDateRange(dateFilter);
      if (dateRange) {
        url += `start_date=${dateRange.start.toISOString()}&end_date=${dateRange.end.toISOString()}&`;
        url += `filter_type=${dateFilter}&`;
      }
      if (linkFilter !== "all") url += `link_id=${linkFilter}&`;
      
      const response = await axios.get(url, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      setClickStats(response.data);
    } catch (error) {
      console.error("Failed to fetch click stats");
    }
  };

  // Calculate stats from loaded clicks (for filtering)
  const ipCounts = {};
  clicks.forEach(c => {
    ipCounts[c.ip_address] = (ipCounts[c.ip_address] || 0) + 1;
  });
  
  // Use API stats for display, local calc for filtering
  const totalClicks = clickStats.count || clicks.length;
  const uniqueIPs = clickStats.unique || Object.keys(ipCounts).length;
  const duplicateIPs = clickStats.duplicate || 0;
  const vpnClicks = clickStats.vpn || clicks.filter(c => c.is_vpn).length;

  // Apply IP filter
  const filteredClicks = clicks.filter(click => {
    if (ipFilter === "unique") return ipCounts[click.ip_address] === 1;
    if (ipFilter === "duplicate") return ipCounts[click.ip_address] > 1;
    if (ipFilter === "vpn") return click.is_vpn;
    if (ipFilter === "clean") return !click.is_vpn;
    return true;
  });

  // Pagination calculations
  const totalPages = Math.ceil(filteredClicks.length / rowsPerPage);
  const startIndex = (currentPage - 1) * rowsPerPage;
  const endIndex = startIndex + rowsPerPage;
  const paginatedClicks = filteredClicks.slice(startIndex, endIndex);

  // Page navigation
  const goToPage = (page) => {
    setCurrentPage(Math.max(1, Math.min(page, totalPages)));
  };

  // Generate page numbers to display
  const getPageNumbers = () => {
    const pages = [];
    const maxVisible = 5;
    let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    
    if (end - start + 1 < maxVisible) {
      start = Math.max(1, end - maxVisible + 1);
    }
    
    for (let i = start; i <= end; i++) {
      pages.push(i);
    }
    return pages;
  };

  // Bulk delete selected
  const handleBulkDelete = async () => {
    if (!window.confirm(`Delete ${selectedClicks.length} clicks?`)) return;
    try {
      await axios.post(`${API}/clicks/bulk-delete`, selectedClicks, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      toast.success("Deleted");
      fetchClicks();
    } catch (error) {
      toast.error("Delete failed");
    }
  };

  // Delete by current filter (date range)
  const handleDeleteByFilter = async () => {
    const dateRange = getDateRange(dateFilter);
    if (!dateRange && dateFilter !== "all") {
      toast.error("Please select a valid date range first");
      return;
    }
    
    const confirmMsg = dateFilter === "all" 
      ? `Delete ALL ${totalClicks} clicks?` 
      : `Delete ${totalClicks} clicks from ${dateFilter === "custom" ? `${customStartDate} to ${customEndDate}` : dateFilter}?`;
    
    if (!window.confirm(confirmMsg)) return;
    
    setDeleting(true);
    try {
      if (dateFilter === "all") {
        const response = await axios.delete(`${API}/clicks/delete-by-date`, {
          params: { all_time: true },
          headers: { Authorization: `Bearer ${getToken()}` },
        });
        toast.success(response.data.message || "All clicks deleted");
      } else if (dateRange) {
        const response = await axios.delete(`${API}/clicks/delete-by-date`, {
          params: { 
            start_date: format(dateRange.start, "yyyy-MM-dd"), 
            end_date: format(dateRange.end, "yyyy-MM-dd") 
          },
          headers: { Authorization: `Bearer ${getToken()}` },
        });
        toast.success(response.data.message || "Clicks deleted");
      }
      fetchClicks();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  // Delete by category (VPN, Proxy, Duplicate)
  const handleDeleteByCategory = async () => {
    const selectedCategories = Object.entries(deleteCategories)
      .filter(([_, selected]) => selected)
      .map(([category]) => category);
    
    if (selectedCategories.length === 0) {
      toast.error("Please select at least one category");
      return;
    }
    
    const categoryNames = selectedCategories.map(c => {
      if (c === 'vpn') return 'VPN';
      if (c === 'proxy') return 'Proxy';
      if (c === 'duplicate') return 'Duplicate';
      return c;
    }).join(', ');
    
    if (!window.confirm(`Delete all clicks marked as: ${categoryNames}?`)) return;
    
    setDeleting(true);
    try {
      const response = await axios.delete(`${API}/clicks/delete-by-category`, {
        params: { categories: selectedCategories.join(',') },
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      toast.success(response.data.message || `Deleted ${categoryNames} clicks`);
      setDeleteByOpen(false);
      setDeleteCategories({ vpn: false, proxy: false, duplicate: false });
      fetchClicks();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  // Quick date filter handler
  const handleQuickDateFilter = (filter) => {
    setDateFilter(filter);
    if (filter !== "custom") {
      setShowCustomDateInputs(false);
    }
  };

  // Apply custom date range
  const applyCustomDateRange = () => {
    if (!customStartDate || !customEndDate) {
      toast.error("Please select both start and end date");
      return;
    }
    setDateFilter("custom");
  };

  // Export to CSV - fetch ALL clicks from server
  const handleExportCSV = async () => {
    setExporting(true);
    try {
      // Build export URL with filters
      let url = `${API}/clicks/export?`;
      // 2026-06 — send explicit start_date+end_date so the export window
      // matches the on-screen table exactly. Previously this only sent
      // `filter_type=month` which the backend interpreted as last-30-days
      // — so CSV downloads contained rows that weren't visible in the UI,
      // OR worse, returned 0 rows when the visible "This Month" had data.
      const dateRange = getDateRange(dateFilter);
      if (dateRange) {
        url += `start_date=${dateRange.start.toISOString()}&end_date=${dateRange.end.toISOString()}&`;
      }
      if (dateFilter !== "all") url += `filter_type=${dateFilter}&`;
      if (linkFilter !== "all") url += `link_id=${linkFilter}&`;
      
      const response = await axios.get(url, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      
      const exportData = response.data.clicks;
      const truncated = response.data.truncated;
      const totalAvailable = response.data.total_available || 0;
      const cap = response.data.cap || 0;
      
      if (!exportData || exportData.length === 0) {
        toast.error("No data to export");
        return;
      }
      
      const headers = ["IPv4", "IPv6", "Proxy IPs", "Country", "City", "Region", "Device", "Browser", "OS", "VPN", "Duplicate", "Link", "Date/Time"];
      const rows = exportData.map(click => [
        click.ipv4 || "",
        click.ipv6 || "",
        click.proxy_ips || "",
        click.country || "",
        click.city || "",
        click.region || "",
        click.device || "",
        click.browser || "",
        click.os || "",
        click.is_vpn || "No",
        click.is_duplicate || "No",
        click.link_name || "",
        click.created_at ? format(new Date(click.created_at), "yyyy-MM-dd HH:mm:ss") : ""
      ]);
      
      const csvContent = [
        headers.join(","),
        ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(","))
      ].join("\n");
      
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const link = document.createElement("a");
      const linkUrl = URL.createObjectURL(blob);
      link.setAttribute("href", linkUrl);
      link.setAttribute("download", `clicks_report_${format(new Date(), "yyyy-MM-dd_HHmm")}.csv`);
      link.style.visibility = "hidden";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      toast.success(`Exported ${exportData.length.toLocaleString()} clicks to CSV`);
      if (truncated) {
        toast.info(
          `Only the newest ${cap.toLocaleString()} clicks were exported ` +
          `(you have ${totalAvailable.toLocaleString()} total). ` +
          `Narrow the date range to export older data.`,
          { duration: 8000 }
        );
      }
    } catch (error) {
      console.error("Export error:", error);
      toast.error("Export failed");
    } finally {
      setExporting(false);
    }
  };

  // Import IPs
  const handleImportIPs = async () => {
    const ips = ipList.split(/[\n,]+/).map(ip => ip.trim()).filter(ip => ip);
    if (ips.length === 0) return toast.error("No IPs");
    
    setImportingIPs(true);
    try {
      const response = await axios.post(`${API}/clicks/import-ips`, {
        ip_list: ips,
        country: ipCountry,
        link_id: selectedLinkId === "none" ? null : selectedLinkId
      }, { headers: { Authorization: `Bearer ${getToken()}` } });
      
      toast.success(`Imported ${response.data.imported} clicks`);
      setShowIPImportDialog(false);
      setIpList("");
      fetchClicks();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Import failed");
    } finally {
      setImportingIPs(false);
    }
  };

  // Select all on current page
  const toggleSelectAll = () => {
    if (selectedClicks.length === paginatedClicks.length) {
      setSelectedClicks([]);
    } else {
      setSelectedClicks(paginatedClicks.map(c => c.id));
    }
  };

  // Get filter label for display
  const getFilterLabel = () => {
    switch (dateFilter) {
      case "today": return "Today";
      case "yesterday": return "Yesterday";
      case "week": return "This Week";
      case "month": return "This Month";
      case "custom": return customStartDate && customEndDate ? `${customStartDate} to ${customEndDate}` : "Custom";
      default: return "All Time";
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin h-8 w-8 text-[#3B82F6]" />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="clicks-page">
      {/* Header */}
      <div className="flex justify-between items-center flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-bold">Clicks</h2>
          <Button
            variant={realTimeEnabled ? "default" : "outline"}
            size="sm"
            onClick={() => setRealTimeEnabled(!realTimeEnabled)}
            className={realTimeEnabled ? "bg-[#22C55E] h-8" : "h-8"}
          >
            {wsConnected ? <Wifi size={12} className="mr-1" /> : <WifiOff size={12} className="mr-1" />}
            {realTimeEnabled ? "Live" : "Real-time"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => fetchClicks(true)} disabled={refreshing} className="h-8">
            <RefreshCw size={12} className={`mr-1 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
        <div className="flex gap-2">
          {selectedClicks.length > 0 && (
            <Button variant="destructive" size="sm" onClick={handleBulkDelete} className="h-8">
              <Trash2 size={12} className="mr-1" />Delete ({selectedClicks.length})
            </Button>
          )}
          
          {/* Export CSV Button */}
          <Button 
            variant="outline" 
            size="sm" 
            onClick={handleExportCSV} 
            disabled={exporting || filteredClicks.length === 0}
            className="h-8 border-[#22C55E] text-[#22C55E] hover:bg-[#22C55E] hover:text-white"
          >
            {exporting ? <Loader2 className="animate-spin mr-1" size={12} /> : <Download size={12} className="mr-1" />}
            Export CSV
          </Button>
          
          {/* Import Dialog */}
          <Dialog open={showIPImportDialog} onOpenChange={setShowIPImportDialog}>
            <DialogTrigger asChild>
              <Button size="sm" className="h-8"><Upload size={12} className="mr-1" />Import</Button>
            </DialogTrigger>
            <DialogContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
              <DialogHeader>
                <DialogTitle>Import IPs</DialogTitle>
                <DialogDescription>Unlimited IP import</DialogDescription>
              </DialogHeader>
              <div className="space-y-3">
                <div>
                  <Label>IP List</Label>
                  <Textarea
                    value={ipList}
                    onChange={(e) => setIpList(e.target.value)}
                    placeholder="One IP per line"
                    className="bg-[var(--brand-card)] border-[var(--brand-border)] h-32"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {ipList.split(/[\n,]+/).filter(ip => ip.trim()).length} IPs
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label>Link</Label>
                    <Select value={selectedLinkId} onValueChange={setSelectedLinkId}>
                      <SelectTrigger className="bg-[var(--brand-card)] border-[var(--brand-border)] h-9">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                        <SelectItem value="none">No link</SelectItem>
                        {links.map(link => (
                          <SelectItem key={link.id} value={link.id}>{link.name || link.short_code}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Country</Label>
                    <Input value={ipCountry} onChange={(e) => setIpCountry(e.target.value)} className="bg-[var(--brand-card)] border-[var(--brand-border)] h-9" />
                  </div>
                </div>
                <Button onClick={handleImportIPs} disabled={importingIPs} className="w-full">
                  {importingIPs ? <Loader2 className="animate-spin mr-1" size={14} /> : null}
                  {importingIPs ? "Importing..." : "Import"}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-2">
        <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">Total</p>
            <p className="text-xl font-bold">{totalClicks.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">Unique</p>
            <p className="text-xl font-bold text-[#22C55E]">{uniqueIPs.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">Duplicate</p>
            <p className="text-xl font-bold text-[#F59E0B]">{duplicateIPs.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">VPN</p>
            <p className="text-xl font-bold text-[#EF4444]">{vpnClicks.toLocaleString()}</p>
          </CardContent>
        </Card>
      </div>

      {/* Date Filter Section */}
      <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
        <CardContent className="p-4 space-y-4">
          {/* Quick Date Buttons */}
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-sm font-medium mr-2">Quick Filters:</span>
            {[
              { key: "today", label: "Today" },
              { key: "yesterday", label: "Yesterday" },
              { key: "week", label: "This Week" },
              { key: "month", label: "This Month" },
              { key: "all", label: "All Time" },
            ].map(f => (
              <Button 
                key={f.key}
                variant={dateFilter === f.key ? "default" : "outline"} 
                size="sm" 
                onClick={() => handleQuickDateFilter(f.key)}
                className={`h-9 ${dateFilter === f.key ? "bg-[#3B82F6]" : ""}`}
              >
                {f.label}
              </Button>
            ))}
          </div>
          
          {/* Custom Date Range */}
          <div className="flex flex-wrap gap-3 items-end border-t border-[var(--brand-border)] pt-4">
            <div>
              <Label className="text-xs text-muted-foreground">Start Date</Label>
              <Input 
                type="date" 
                value={customStartDate}
                onChange={(e) => setCustomStartDate(e.target.value)}
                className="bg-[var(--brand-card)] border-[var(--brand-border)] h-9 w-40"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">End Date</Label>
              <Input 
                type="date" 
                value={customEndDate}
                onChange={(e) => setCustomEndDate(e.target.value)}
                className="bg-[var(--brand-card)] border-[var(--brand-border)] h-9 w-40"
              />
            </div>
            <Button 
              onClick={applyCustomDateRange}
              disabled={!customStartDate || !customEndDate}
              className="h-9 bg-[#8B5CF6] hover:bg-[#7C3AED]"
            >
              <Eye size={14} className="mr-1" />
              View Report
            </Button>
            
            {/* Delete By Dropdown */}
            <Popover open={deleteByOpen} onOpenChange={setDeleteByOpen}>
              <PopoverTrigger asChild>
                <Button variant="destructive" className="h-9">
                  <Trash2 size={14} className="mr-1" />
                  Delete By
                  <ChevronDown size={14} className="ml-1" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-56 bg-[var(--brand-card)] border-[var(--brand-border)] p-4">
                <div className="space-y-3">
                  <h4 className="font-medium text-sm">Delete clicks by category:</h4>
                  <div className="space-y-2">
                    <div className="flex items-center space-x-2">
                      <Checkbox 
                        id="delete-vpn" 
                        checked={deleteCategories.vpn}
                        onCheckedChange={(checked) => setDeleteCategories(prev => ({ ...prev, vpn: checked }))}
                      />
                      <label htmlFor="delete-vpn" className="text-sm flex items-center gap-1">
                        <Wifi size={12} className="text-[#EF4444]" />
                        VPN/Hosting
                      </label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox 
                        id="delete-proxy" 
                        checked={deleteCategories.proxy}
                        onCheckedChange={(checked) => setDeleteCategories(prev => ({ ...prev, proxy: checked }))}
                      />
                      <label htmlFor="delete-proxy" className="text-sm flex items-center gap-1">
                        <WifiOff size={12} className="text-[#F59E0B]" />
                        Proxy Detected
                      </label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox 
                        id="delete-duplicate" 
                        checked={deleteCategories.duplicate}
                        onCheckedChange={(checked) => setDeleteCategories(prev => ({ ...prev, duplicate: checked }))}
                      />
                      <label htmlFor="delete-duplicate" className="text-sm flex items-center gap-1">
                        <RefreshCw size={12} className="text-[#8B5CF6]" />
                        Duplicate IP
                      </label>
                    </div>
                  </div>
                  <Button 
                    variant="destructive" 
                    size="sm" 
                    onClick={handleDeleteByCategory}
                    disabled={deleting || !Object.values(deleteCategories).some(v => v)}
                    className="w-full"
                  >
                    {deleting ? <Loader2 className="animate-spin mr-1" size={14} /> : <Trash2 size={14} className="mr-1" />}
                    Delete Selected
                  </Button>
                </div>
              </PopoverContent>
            </Popover>
            
            <Button 
              variant="destructive"
              onClick={handleDeleteByFilter}
              disabled={deleting || totalClicks === 0}
              className="h-9"
            >
              {deleting ? <Loader2 className="animate-spin mr-1" size={14} /> : <Trash2 size={14} className="mr-1" />}
              Delete {getFilterLabel()} ({totalClicks})
            </Button>
          </div>
          
          {/* Current Filter Display */}
          {dateFilter !== "all" && (
            <div className="text-sm text-muted-foreground bg-[var(--brand-card)] p-2 rounded">
              Showing: <span className="text-white font-medium">{getFilterLabel()}</span> - {totalClicks} clicks
            </div>
          )}
        </CardContent>
      </Card>

      {/* Filters & Table */}
      <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
        <CardHeader className="py-3 px-4">
          <div className="flex flex-wrap gap-2 items-center justify-between">
            <div className="flex flex-wrap gap-2 items-center">
              {/* IP Filter */}
              {[
                { key: "all", label: "All IPs" },
                { key: "unique", label: "Unique", color: "#22C55E" },
                { key: "duplicate", label: "Dup", color: "#F59E0B" },
                { key: "vpn", label: "VPN", color: "#EF4444" }
              ].map(f => (
                <Button
                  key={f.key}
                  variant={ipFilter === f.key ? "default" : "outline"}
                  size="sm"
                  onClick={() => setIpFilter(f.key)}
                  className="h-7 text-xs"
                  style={ipFilter !== f.key && f.color ? { borderColor: f.color, color: f.color } : {}}
                >
                  {f.label}
                </Button>
              ))}
              <span className="mx-1 text-[#27272A]">|</span>
              {/* Link Filter */}
              <Select value={linkFilter} onValueChange={setLinkFilter}>
                <SelectTrigger className="w-[140px] bg-[var(--brand-card)] border-[var(--brand-border)] h-7 text-xs">
                  <SelectValue placeholder="All Links" />
                </SelectTrigger>
                <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                  <SelectItem value="all">All Links</SelectItem>
                  {links.map(link => (
                    <SelectItem key={link.id} value={link.id}>{link.name || link.short_code}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {/* Rows per page */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Rows:</span>
              <Select value={rowsPerPage.toString()} onValueChange={(v) => setRowsPerPage(parseInt(v))}>
                <SelectTrigger className="w-[70px] bg-[var(--brand-card)] border-[var(--brand-border)] h-7 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[var(--brand-card)] border-[var(--brand-border)]">
                  {[25, 50, 100, 200, 500].map(n => (
                    <SelectItem key={n} value={n.toString()}>{n}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {/* Pagination Controls - TOP */}
          <div className="p-3 border-b border-[var(--brand-border)] flex flex-wrap justify-between items-center gap-2">
            <span className="text-xs text-muted-foreground">
              Showing {filteredClicks.length > 0 ? startIndex + 1 : 0}-{Math.min(endIndex, filteredClicks.length)} of {totalClicks.toLocaleString()} clicks
              {ipFilter !== "all" && ` (${filteredClicks.length.toLocaleString()} filtered)`}
            </span>
            
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <Button variant="outline" size="sm" onClick={() => goToPage(1)} disabled={currentPage === 1} className="h-7 w-7 p-0">
                  <ChevronsLeft size={14} />
                </Button>
                <Button variant="outline" size="sm" onClick={() => goToPage(currentPage - 1)} disabled={currentPage === 1} className="h-7 w-7 p-0">
                  <ChevronLeft size={14} />
                </Button>
                {getPageNumbers().map(page => (
                  <Button
                    key={page}
                    variant={currentPage === page ? "default" : "outline"}
                    size="sm"
                    onClick={() => goToPage(page)}
                    className="h-7 min-w-[28px] px-2 text-xs"
                  >
                    {page}
                  </Button>
                ))}
                <Button variant="outline" size="sm" onClick={() => goToPage(currentPage + 1)} disabled={currentPage === totalPages} className="h-7 w-7 p-0">
                  <ChevronRight size={14} />
                </Button>
                <Button variant="outline" size="sm" onClick={() => goToPage(totalPages)} disabled={currentPage === totalPages} className="h-7 w-7 p-0">
                  <ChevronsRight size={14} />
                </Button>
                <span className="text-xs text-muted-foreground ml-2">Page {currentPage}/{totalPages}</span>
              </div>
            )}
          </div>
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-[var(--brand-border)]">
                  <TableHead className="w-8 p-2">
                    <input
                      type="checkbox"
                      checked={paginatedClicks.length > 0 && selectedClicks.length === paginatedClicks.length}
                      onChange={toggleSelectAll}
                      className="w-3 h-3"
                    />
                  </TableHead>
                  <TableHead className="p-2 text-xs">IPv4</TableHead>
                  <TableHead className="p-2 text-xs">IPv6</TableHead>
                  <TableHead className="p-2 text-xs">Proxy IPs</TableHead>
                  <TableHead className="p-2 text-xs">Country</TableHead>
                  <TableHead className="p-2 text-xs">City</TableHead>
                  <TableHead className="p-2 text-xs">Region</TableHead>
                  <TableHead className="p-2 text-xs">Device</TableHead>
                  <TableHead className="p-2 text-xs">Browser</TableHead>
                  <TableHead className="p-2 text-xs">OS</TableHead>
                  <TableHead className="p-2 text-xs">VPN</TableHead>
                  <TableHead className="p-2 text-xs">Link</TableHead>
                  <TableHead className="p-2 text-xs">Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedClicks.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={13} className="text-center py-8 text-muted-foreground">No clicks found</TableCell>
                  </TableRow>
                ) : (
                  paginatedClicks.map((click) => (
                    <TableRow key={click.id} className="border-[var(--brand-border)] h-9">
                      <TableCell className="p-2">
                        <input
                          type="checkbox"
                          checked={selectedClicks.includes(click.id)}
                          onChange={() => {
                            setSelectedClicks(prev =>
                              prev.includes(click.id) ? prev.filter(id => id !== click.id) : [...prev, click.id]
                            );
                          }}
                          className="w-3 h-3"
                        />
                      </TableCell>
                      <TableCell className="p-2 font-mono text-xs">
                        {click.ipv4 || (click.ipv6 ? "-" : (click.ip_address || "-"))}
                      </TableCell>
                      <TableCell className="p-2 font-mono text-xs text-muted-foreground">
                        {click.ipv6 ? (
                          <span title={click.ipv6}>{click.ipv6.length > 16 ? click.ipv6.slice(0, 16) + "..." : click.ipv6}</span>
                        ) : "-"}
                      </TableCell>
                      <TableCell className="p-2 font-mono text-xs text-muted-foreground">
                        {click.proxy_ips && click.proxy_ips.length > 0 ? (
                          <span title={click.proxy_ips.join(", ")}>
                            {click.proxy_ips[0].length > 12 ? click.proxy_ips[0].slice(0, 12) + "..." : click.proxy_ips[0]}
                            {click.proxy_ips.length > 1 && ` +${click.proxy_ips.length - 1}`}
                          </span>
                        ) : "-"}
                      </TableCell>
                      <TableCell className="p-2 text-xs">{click.country || "-"}</TableCell>
                      <TableCell className="p-2 text-xs">{click.city || "-"}</TableCell>
                      <TableCell className="p-2 text-xs">{click.region || "-"}</TableCell>
                      <TableCell className="p-2 text-xs">{click.device_type || click.device || "-"}</TableCell>
                      <TableCell className="p-2 text-xs">{click.browser || "-"}</TableCell>
                      <TableCell className="p-2 text-xs">{click.os_name || "-"}</TableCell>
                      <TableCell className="p-2">
                        {click.is_vpn ? (
                          <span className="text-[#EF4444] text-xs font-medium">VPN</span>
                        ) : (
                          <span className="text-[#22C55E] text-xs">✓</span>
                        )}
                      </TableCell>
                      <TableCell className="p-2 text-xs">{getLinkName(click.link_id)}</TableCell>
                      <TableCell className="p-2 text-xs text-muted-foreground">
                        {click.created_at ? format(new Date(click.created_at), "MM/dd HH:mm") : "-"}
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
