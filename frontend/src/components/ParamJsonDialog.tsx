import { useState, useEffect, useCallback } from "react";
import Editor from "@monaco-editor/react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useStrategyStore } from "@/stores/strategyStore";

/** Keys managed by the sidebar — exclude from the JSON editor. */
const SIDEBAR_KEYS = new Set([
  "bar_agg",
  "max_loss",
  "slippage_bps",
  "commission_fixed_per_contract",
]);

/** Extract strategy-specific params as a formatted JSON string. */
function paramsToJson(params: Record<string, number>): string {
  const filtered: Record<string, number> = {};
  for (const [k, v] of Object.entries(params)) {
    if (!SIDEBAR_KEYS.has(k)) filtered[k] = v;
  }
  return JSON.stringify(filtered, null, 2);
}

export function ParamJsonDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const params = useStrategyStore((s) => s.params);
  const setParams = useStrategyStore((s) => s.setParams);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  // Sync draft when dialog opens or params change while open
  useEffect(() => {
    if (open) {
      setDraft(paramsToJson(params));
      setError("");
    }
  }, [open, params]);

  const handleApply = useCallback(() => {
    try {
      const parsed = JSON.parse(draft);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setError("Must be a JSON object");
        return;
      }
      for (const [k, v] of Object.entries(parsed)) {
        if (typeof v !== "number") {
          setError(`Value for "${k}" must be a number`);
          return;
        }
      }
      // Preserve sidebar-managed keys from current params
      const merged: Record<string, number> = { ...parsed };
      for (const key of SIDEBAR_KEYS) {
        if (key in params) merged[key] = params[key];
      }
      setParams(merged);
      onOpenChange(false);
    } catch {
      setError("Invalid JSON");
    }
  }, [draft, params, setParams, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        style={{
          background: "var(--color-qe-card)",
          border: "1px solid var(--color-qe-card-border)",
          color: "var(--color-qe-text)",
        }}
      >
        <DialogHeader>
          <DialogTitle
            style={{ color: "var(--color-qe-text)", fontSize: 13 }}
          >
            Strategy Parameters
          </DialogTitle>
        </DialogHeader>
        <div
          className="rounded overflow-hidden"
          style={{
            border: "1px solid var(--color-qe-input-border)",
            height: 300,
          }}
        >
          <Editor
            height="100%"
            language="json"
            theme="vs-dark"
            value={draft}
            onChange={(v) => {
              setDraft(v ?? "");
              setError("");
            }}
            options={{
              minimap: { enabled: false },
              lineNumbers: "off",
              scrollBeyondLastLine: false,
              fontSize: 12,
              tabSize: 2,
              automaticLayout: true,
              wordWrap: "on",
            }}
          />
        </div>
        {error && (
          <p className="text-[11px]" style={{ color: "#ef4444" }}>
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            style={{
              borderColor: "var(--color-qe-input-border)",
              color: "var(--color-qe-text-muted)",
            }}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleApply}
            style={{
              background: "var(--color-qe-accent)",
              color: "#fff",
            }}
          >
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
