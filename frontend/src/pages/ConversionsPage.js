import { useEffect, useState } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import { format } from "date-fns";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function ConversionsPage() {
  const [conversions, setConversions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchConversions();
  }, []);

  const fetchConversions = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get(`${API}/conversions?limit=200`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setConversions(response.data);
    } catch (error) {
      toast.error("Failed to fetch conversions");
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case "approved":
        return "bg-[#22C55E]";
      case "pending":
        return "bg-[#F59E0B]";
      case "rejected":
        return "bg-[#EF4444]";
      default:
        return "bg-[#A1A1AA]";
    }
  };

  if (loading) {
    return <div className="text-muted-foreground">Loading conversions...</div>;
  }

  const totalRevenue = conversions.reduce((sum, conv) => sum + conv.payout, 0);

  return (
    <div className="space-y-6" data-testid="conversions-page">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Conversions</h2>
        <div className="text-right">
          <div className="text-sm text-muted-foreground">Total Revenue</div>
          <div className="text-2xl font-bold font-mono text-[#22C55E]">
            ${totalRevenue.toFixed(2)}
          </div>
        </div>
      </div>

      <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
        <CardHeader>
          <CardTitle>All Conversions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-[var(--brand-border)] hover:bg-transparent">
                  <TableHead>Click ID</TableHead>
                  <TableHead>IP Address</TableHead>
                  <TableHead className="text-right">Payout</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Timestamp</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {conversions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                      No conversions recorded yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  conversions.map((conversion) => (
                    <TableRow key={conversion.id} className="border-[var(--brand-border)]" data-testid={`conversion-row-${conversion.id}`}>
                      <TableCell className="font-mono text-xs">{conversion.click_id.slice(0, 8)}...</TableCell>
                      <TableCell className="font-mono text-xs">{conversion.ip_address}</TableCell>
                      <TableCell className="text-right font-mono font-semibold text-[#22C55E]">
                        ${conversion.payout.toFixed(2)}
                      </TableCell>
                      <TableCell>
                        <Badge className={getStatusColor(conversion.status)}>{conversion.status}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {format(new Date(conversion.created_at), "MMM dd, yyyy HH:mm")}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-[var(--brand-card)] border-[var(--brand-border)]">
        <CardHeader>
          <CardTitle>Conversion Tracking Setup</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h4 className="text-sm font-semibold mb-2">Method 1: Postback URL (S2S)</h4>
            <p className="text-sm text-muted-foreground mb-2">
              Configure this URL in your affiliate network to receive conversion notifications:
            </p>
            <code className="block bg-[var(--brand-card)] p-3 rounded-md text-xs font-mono break-all">
              {BACKEND_URL}/api/postback?clickid=&#123;clickid&#125;&amp;payout=&#123;payout&#125;&amp;status=approved&amp;token=YOUR_POSTBACK_TOKEN
            </code>
            <p className="text-xs text-muted-foreground mt-2">
              GET or POST. Networks may send clickid, transaction_id, sub1, cid, amount, sale, or payout — all accepted.
            </p>
          </div>

          <div>
            <h4 className="text-sm font-semibold mb-2">Method 2: Pixel Tracking</h4>
            <p className="text-sm text-muted-foreground mb-2">
              Place this pixel on your conversion/thank you page:
            </p>
            <code className="block bg-[var(--brand-card)] p-3 rounded-md text-xs font-mono break-all">
              &lt;img src="{BACKEND_URL}/api/pixel?clickid=CLICK_ID&amp;payout=AMOUNT" width="1" height="1" /&gt;
            </code>
          </div>

          <div className="bg-[var(--brand-card)] p-4 rounded-md">
            <p className="text-sm text-muted-foreground">
              <strong className="text-white">Note:</strong> The clickid parameter is automatically appended to your
              offer URL when a visitor clicks your tracking link. Make sure to pass it to your conversion tracking.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
