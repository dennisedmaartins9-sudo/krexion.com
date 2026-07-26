import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Switch } from "./ui/switch";
import { Badge } from "./ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { toast } from "sonner";
import { Shield, Plus, Pencil, Trash2, Users, RefreshCw } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function CrossUserIpIsolationPanel({ users = [], getAdminToken }) {
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingGroup, setEditingGroup] = useState(null);
  const [groupName, setGroupName] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState([]);
  const [groupEnabled, setGroupEnabled] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchGroups = useCallback(async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API}/admin/cross-user-ip-groups`, {
        headers: { Authorization: `Bearer ${getAdminToken()}` },
      });
      setGroups(res.data?.groups || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to load IP isolation groups");
    } finally {
      setLoading(false);
    }
  }, [getAdminToken]);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  const openCreate = () => {
    setEditingGroup(null);
    setGroupName("");
    setSelectedUserIds([]);
    setGroupEnabled(true);
    setDialogOpen(true);
  };

  const openEdit = (group) => {
    setEditingGroup(group);
    setGroupName(group.name || "");
    setSelectedUserIds(group.user_ids || []);
    setGroupEnabled(group.enabled !== false);
    setDialogOpen(true);
  };

  const toggleUser = (userId) => {
    setSelectedUserIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const handleSave = async () => {
    if (selectedUserIds.length < 2) {
      return toast.error("Kam az kam 2 users select karein");
    }
    setSaving(true);
    try {
      const headers = { Authorization: `Bearer ${getAdminToken()}` };
      const payload = {
        name: groupName.trim() || "Isolation Group",
        user_ids: selectedUserIds,
        enabled: groupEnabled,
      };
      if (editingGroup?.id) {
        await axios.put(`${API}/admin/cross-user-ip-groups/${editingGroup.id}`, payload, { headers });
        toast.success("Group update ho gaya");
      } else {
        await axios.post(`${API}/admin/cross-user-ip-groups`, payload, { headers });
        toast.success("Naya group ban gaya");
      }
      setDialogOpen(false);
      fetchGroups();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (groupId) => {
    if (!window.confirm("Is group ko delete karein? In users alag ho jayenge.")) return;
    try {
      await axios.delete(`${API}/admin/cross-user-ip-groups/${groupId}`, {
        headers: { Authorization: `Bearer ${getAdminToken()}` },
      });
      toast.success("Group delete ho gaya");
      fetchGroups();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Delete failed");
    }
  };

  const assignedElsewhere = (userId, currentGroupId) => {
    return groups.some(
      (g) => g.id !== currentGroupId && (g.user_ids || []).includes(userId)
    );
  };

  return (
    <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
      <CardHeader>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <CardTitle className="text-white flex items-center gap-2">
              <Shield size={20} />
              Cross-User IP Isolation
            </CardTitle>
            <CardDescription className="mt-2 max-w-3xl">
              Admin yahan users ko group mein select kare. Ek group ke andar koi b user doosre user ka
              exit IP dubara use nahi kar sakta — RUT job chalte waqt duplicate IP skip hogi. Jo users
              group mein nahi, unka IP pool alag rehta hai.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={fetchGroups} disabled={loading}>
              <RefreshCw size={14} className="mr-1" />
              Refresh
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus size={14} className="mr-1" />
              New Group
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-muted-foreground text-sm">Loading groups…</p>
        ) : groups.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--brand-border)] p-8 text-center text-muted-foreground">
            <Users className="mx-auto mb-3 opacity-50" size={32} />
            <p>Abhi koi isolation group nahi. Ali + Usman + Shahbaz jaisa group banayein taake unke IPs match na hon.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {groups.map((group) => (
              <div
                key={group.id}
                className="rounded-lg border border-[var(--brand-border)] p-4 bg-[#18181B]/50"
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-medium text-white">{group.name}</h3>
                      <Badge variant={group.enabled !== false ? "default" : "secondary"}>
                        {group.enabled !== false ? "Active" : "Disabled"}
                      </Badge>
                      <Badge variant="outline">{(group.members || []).length} users</Badge>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {(group.members || []).map((m) => (
                        <Badge key={m.id} variant="secondary" className="font-normal">
                          {m.name || m.email}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => openEdit(group)}>
                      <Pencil size={14} className="mr-1" />
                      Edit
                    </Button>
                    <Button variant="destructive" size="sm" onClick={() => handleDelete(group.id)}>
                      <Trash2 size={14} className="mr-1" />
                      Delete
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{editingGroup ? "Edit Isolation Group" : "New Isolation Group"}</DialogTitle>
              <DialogDescription>
                Jo users select honge, un sab ka click / RUT IP history shared blocklist ban jayegi.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div>
                <Label>Group name</Label>
                <Input
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                  placeholder="e.g. Team Alpha"
                  className="mt-1"
                />
              </div>
              <div className="flex items-center justify-between">
                <Label>Enabled</Label>
                <Switch checked={groupEnabled} onCheckedChange={setGroupEnabled} />
              </div>
              <div>
                <Label className="mb-2 block">Users (min 2)</Label>
                <div className="max-h-64 overflow-y-auto space-y-2 rounded-md border p-3">
                  {users.map((u) => {
                    const elsewhere = assignedElsewhere(u.id, editingGroup?.id);
                    const checked = selectedUserIds.includes(u.id);
                    return (
                      <label
                        key={u.id}
                        className={`flex items-center gap-2 text-sm cursor-pointer ${elsewhere && !checked ? "opacity-50" : ""}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={elsewhere && !checked}
                          onChange={() => toggleUser(u.id)}
                        />
                        <span>{u.name || u.email}</span>
                        <span className="text-muted-foreground text-xs">{u.email}</span>
                        {elsewhere && !checked && (
                          <Badge variant="outline" className="text-xs ml-auto">other group</Badge>
                        )}
                      </label>
                    );
                  })}
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  Selected: {selectedUserIds.length} — har user sirf ek group mein ho sakta hai.
                </p>
              </div>
              <Button onClick={handleSave} disabled={saving || selectedUserIds.length < 2} className="w-full">
                {saving ? "Saving…" : editingGroup ? "Update Group" : "Create Group"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
