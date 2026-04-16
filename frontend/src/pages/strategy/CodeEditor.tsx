import { useEffect, useState, useCallback } from "react";
import { Sidebar, SectionLabel } from "@/components/Sidebar";
import { fetchEditorFiles, fetchEditorFile, writeEditorFile, validateEngine } from "@/lib/api";
import type { EditorFile } from "@/lib/api";
import { colors } from "@/lib/theme";
import Editor from "@monaco-editor/react";

export function CodeEditor() {
  const [files, setFiles] = useState<EditorFile[]>([]);
  const [selected, setSelected] = useState("");
  const [content, setContent] = useState("");
  const [original, setOriginal] = useState("");
  const [validation, setValidation] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    fetchEditorFiles().then(setFiles).catch(() => {});
  }, []);

  const loadFile = useCallback(async (path: string) => {
    try {
      const r = await fetchEditorFile(path);
      setContent(r.content);
      setOriginal(r.content);
      setSelected(path);
      setDirty(false);
      setValidation([]);
    } catch {
      // ignore
    }
  }, []);

  const handleSave = async () => {
    if (!selected) return;
    const r = await writeEditorFile(selected, content);
    const msgs: string[] = [];
    if (!r.syntax.ok) msgs.push(`Syntax error line ${r.syntax.line}: ${r.syntax.msg}`);
    r.ruff.forEach((i) => msgs.push(`L${i.line} [${i.rule}] ${i.msg}`));
    if (msgs.length === 0) msgs.push("Saved OK");
    setValidation(msgs);
    setOriginal(content);
    setDirty(false);
  };

  const handleRevert = () => {
    setContent(original);
    setDirty(false);
    setValidation([]);
  };

  const handleValidate = async () => {
    const r = await validateEngine();
    setValidation(r.ok ? ["Engine validation OK"] : [`Engine error: ${r.error}`]);
  };

  const grouped = files.reduce<Record<string, EditorFile[]>>((acc, f) => {
    (acc[f.dir] ??= []).push(f);
    return acc;
  }, {});

  return (
    <div className="flex" style={{ height: "calc(100vh - 130px)" }}>
      <Sidebar>
        <SectionLabel>FILES</SectionLabel>
        <div className="overflow-y-auto" style={{ maxHeight: "calc(100vh - 200px)" }}>
          {Object.entries(grouped).map(([dir, items]) => (
            <div key={dir}>
              <div className="text-[11px] uppercase tracking-[1.5px] px-2 pt-2 pb-0.5" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                {dir}/
              </div>
              {items.map((f) => (
                <div
                  key={f.path}
                  onClick={() => loadFile(f.path)}
                  className="text-[11px] py-1 px-4 cursor-pointer rounded-sm"
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: selected === f.path ? colors.text : colors.muted,
                    background: selected === f.path ? colors.card : "transparent",
                  }}
                >
                  {f.name}
                </div>
              ))}
            </div>
          ))}
        </div>
      </Sidebar>
      <div className="flex-1 flex flex-col p-3" style={{ minWidth: 0 }}>
        {/* File header */}
        <div className="flex items-center mb-2 gap-2">
          <span className="text-[12px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
            {selected || "No file selected"}
          </span>
          {dirty && (
            <span className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.gold }}>
              (modified)
            </span>
          )}
        </div>
        {/* Code editor */}
        <div className="flex-1 rounded overflow-hidden" style={{ border: `1px solid ${colors.cardBorder}` }}>
          <Editor
            height="100%"
            defaultLanguage="python"
            value={content}
            onChange={(val) => {
              setContent(val ?? "");
              setDirty(val !== original);
            }}
            theme="vs-dark"
            options={{
              fontSize: 13,
              fontFamily: "var(--font-mono)",
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              lineNumbers: "on",
              renderLineHighlight: "line",
              tabSize: 4,
              insertSpaces: true,
              automaticLayout: true,
              wordWrap: "on",
              padding: { top: 8, bottom: 8 },
            }}
          />
        </div>
        {/* Actions */}
        <div className="flex gap-2 mt-2">
          <button onClick={handleSave} disabled={!selected} className="px-4 py-1.5 rounded text-[11px] font-semibold border-none text-white cursor-pointer" style={{ background: "#2A7A4A", fontFamily: "var(--font-mono)" }}>
            Save
          </button>
          <button onClick={handleRevert} disabled={!dirty} className="px-4 py-1.5 rounded text-[11px] border cursor-pointer" style={{ background: colors.card, color: colors.muted, borderColor: colors.cardBorder, fontFamily: "var(--font-mono)" }}>
            Revert
          </button>
          <button onClick={handleValidate} disabled={!selected} className="px-4 py-1.5 rounded text-[11px] border cursor-pointer" style={{ background: colors.card, color: colors.cyan, borderColor: colors.cardBorder, fontFamily: "var(--font-mono)" }}>
            Validate Engine
          </button>
        </div>
        {/* Validation panel */}
        {validation.length > 0 && (
          <details open className="mt-2">
            <summary className="text-[11px] cursor-pointer" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>Validation</summary>
            <div className="p-2 mt-1 rounded max-h-[200px] overflow-y-auto" style={{ background: colors.sidebar, border: `1px solid ${colors.cardBorder}` }}>
              {validation.map((msg, i) => (
                <div key={i} className="text-[11px] leading-relaxed" style={{ fontFamily: "var(--font-mono)", color: msg.includes("OK") ? colors.green : colors.red }}>
                  {msg}
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
