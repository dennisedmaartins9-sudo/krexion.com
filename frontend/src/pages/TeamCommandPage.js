import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import {
  Activity,
  Cpu,
  HardDrive,
  Monitor,
  RefreshCw,
  Shield,
  Users,
  Wifi,
  WifiOff,
  Fingerprint,
  Link2,
  Globe,
  Clock,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Switch } from "../components/ui/switch";
import { Label } from "../components/ui/label";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const authH = () => ({
  Authorization: `Bearer ${localStorage.getItem("token")}`,
});

const PERM_META = [
  { key: "rut", label: "Real User Traffic", icon: Fingerprint },
  { key: "links", label: "Links", icon: Link2 },
  { key: "profiles", label: "Browser Profiles", icon: Globe },
];

function OnlineBadge({ online, secAgo }) {
  if (online) {
    return (
      <Badge className="bg-emerald-600/20 text-emerald-300 border-emerald-500/40">
        <Wifi size={12} className="mr-1" /> Online
        {secAgo != null ? ` · ${secAgo}s ago` : ""}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-zinc-400 border-zinc-600">
      <WifiOff size={12} className="mr-1" /> Offline
    </Badge>
  );
}

export default function TeamCommandPage() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [members, setMembers] = useState([]);
  const [audit, setAudit] = useState([]);
  const [savingMember, setSavingMember] = useState(null);

  const loadAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const [settingsRes, membersRes, auditRes] = await Promise.all([
        axios.get(`${API}/team-fleet/settings`, { headers: authH() }),
        axios.get(`${API}/team-fleet/members`, { headers: authH() }),
        axios.get(`${API}/team-fleet/audit?limit=30`, { headers: authH() }),
      ]);
      setEnabled(!!settingsRes.data?.enabled);
      setMembers(membersRes.data?.members || []);
      setAudit(auditRes.data?.items || []);
    } catch (err) {
      const msg = err.response?.data?.detail || "Failed to load Team Fleet";
      toast.error(typeof msg === "string" ? msg : "Team Fleet unavailable");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    const t = setInterval(() => loadAll(true), 15000);
    return () => clearInterval(t);
  }, [loadAll]);

  const toggleFleet = async (next) => {
    try {
      await axios.put(
        `${API}/team-fleet/settings`,
        { enabled: next },
        { headers: authH() },
      );
      setEnabled(next);
      toast.success(next ? "Team Fleet Control enabled" : "Team Fleet Control disabled");
      loadAll(true);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not update fleet setting");
    }
  };

  const updateMember = async (memberId, patch) => {
    setSavingMember(memberId);
    try {
      await axios.put(`${API}/team-fleet/members/${memberId}`, patch, { headers: authH() });
      toast.success("Member fleet settings saved");
      loadAll(true);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Update failed");
    } finally {
      setSavingMember(null);
    }
  };

  const toggleMemberAllowed = (member) => {
    updateMember(member.id, { fleet_control_allowed: !member.fleet_control_allowed });
  };

  const toggleMemberPerm = (member, key) => {
    const perms = { ...(member.fleet_permissions || {}) };
    perms[key] = !perms[key];
    updateMember(member.id, { fleet_permissions: perms });
  };

  if (loading) {
    return (
      <div className="p-6 text-zinc-400" data-testid="team-command-loading">
        Loading Team Command Center…
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-6xl mx-auto" data-testid="team-command-page">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Users className="text-[#4F7FFF]" size={28} />
            Team Command Center
          </h1>
          <p className="text-zinc-400 mt-1 text-sm max-w-2xl">
            Control your team members&apos; native PCs from one dashboard. Heavy work runs on
            each member&apos;s computer — the cloud only queues jobs and shows live status.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadAll(true)}
            disabled={refreshing}
            data-testid="team-command-refresh"
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin mr-1" : "mr-1"} />
            Refresh
          </Button>
          <div className="flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 bg-zinc-900/60">
            <Label htmlFor="fleet-master-toggle" className="text-sm text-zinc-300">
              Fleet Control
            </Label>
            <Switch
              id="fleet-master-toggle"
              checked={enabled}
              onCheckedChange={toggleFleet}
              data-testid="team-fleet-master-toggle"
            />
          </div>
        </div>
      </div>

      {!enabled && (
        <Card className="border-amber-500/30 bg-amber-950/20">
          <CardContent className="pt-6 text-amber-100/90 text-sm">
            Team Fleet is <strong>OFF</strong>. Enable the toggle above (or in Settings) to see
            member PCs and delegate RUT / links / profiles to their native installs.
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {members.map((m) => {
          const st = m.local_status || {};
          return (
            <Card key={m.id} className="border-zinc-800 bg-zinc-950/80" data-testid={`fleet-member-${m.id}`}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <CardTitle className="text-base text-white truncate">{m.name || m.email}</CardTitle>
                    <CardDescription className="truncate">{m.email}</CardDescription>
                  </div>
                  <OnlineBadge online={m.online} secAgo={st.last_seen_sec_ago} />
                </div>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="grid grid-cols-2 gap-2 text-zinc-400">
                  <span className="flex items-center gap-1">
                    <Monitor size={13} /> {st.hostname || "—"}
                  </span>
                  <span className="flex items-center gap-1">
                    <HardDrive size={13} /> {st.ram_gb ? `${st.ram_gb} GB RAM` : "—"}
                  </span>
                  <span className="flex items-center gap-1">
                    <Cpu size={13} /> {st.cpu_cores ? `${st.cpu_cores} cores` : "—"}
                  </span>
                  <span className="flex items-center gap-1 truncate">
                    <Activity size={13} /> {st.version || "—"}
                  </span>
                </div>

                {!m.is_active && (
                  <Badge variant="destructive" className="text-xs">Account deactivated</Badge>
                )}

                <div className="flex items-center justify-between pt-1 border-t border-zinc-800">
                  <span className="text-zinc-400 flex items-center gap-1">
                    <Shield size={13} /> Allow fleet control
                  </span>
                  <Switch
                    checked={!!m.fleet_control_allowed}
                    disabled={!enabled || savingMember === m.id}
                    onCheckedChange={() => toggleMemberAllowed(m)}
                    data-testid={`fleet-allow-${m.id}`}
                  />
                </div>

                {m.fleet_control_allowed && (
                  <div className="space-y-1">
                    {PERM_META.map(({ key, label, icon: Icon }) => (
                      <div key={key} className="flex items-center justify-between">
                        <span className="text-zinc-400 flex items-center gap-1 text-xs">
                          <Icon size={12} /> {label}
                        </span>
                        <Switch
                          checked={!!(m.fleet_permissions || {})[key]}
                          disabled={!enabled || savingMember === m.id}
                          onCheckedChange={() => toggleMemberPerm(m, key)}
                        />
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex flex-wrap gap-2 pt-2">
                  <Button
                    asChild
                    size="sm"
                    variant="secondary"
                    disabled={!enabled || !m.fleet_control_allowed || !m.online}
                    className="text-xs"
                  >
                    <Link
                      to={`/real-user-traffic?fleet_member=${m.id}`}
                      data-testid={`fleet-rut-${m.id}`}
                    >
                      <Fingerprint size={13} className="mr-1" />
                      Start RUT here
                    </Link>
                  </Button>
                </div>

                {m.last_rut_job_id && (
                  <p className="text-xs text-zinc-500 truncate">
                    Last RUT job: {m.last_rut_job_id.slice(0, 12)}…
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {enabled && members.length === 0 && (
        <Card className="border-zinc-800">
          <CardContent className="pt-6 text-zinc-400 text-sm">
            No sub-users yet. Create team members in{" "}
            <Link to="/settings" className="text-[#4F7FFF] underline">
              Settings → Sub-Users
            </Link>
            , then pair each member&apos;s native install with their sub-user email/license.
          </CardContent>
        </Card>
      )}

      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader>
          <CardTitle className="text-white text-lg flex items-center gap-2">
            <Clock size={18} /> Recent fleet actions
          </CardTitle>
          <CardDescription>Audit log for delegated commands (last 30)</CardDescription>
        </CardHeader>
        <CardContent>
          {audit.length === 0 ? (
            <p className="text-zinc-500 text-sm">No fleet actions yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {audit.map((a) => (
                <li
                  key={a.id}
                  className="flex flex-wrap gap-x-3 gap-y-1 text-zinc-400 border-b border-zinc-800/80 pb-2"
                >
                  <span className="text-zinc-300">{a.action}</span>
                  {a.member_email && <span>→ {a.member_email}</span>}
                  {a.feature && <span className="text-zinc-500">{a.feature}</span>}
                  <span className="text-zinc-600 ml-auto text-xs">{a.created_at?.slice(0, 19)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
