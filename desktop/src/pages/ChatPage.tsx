import React, { useState, useEffect, useRef } from "react";
import { api } from "../api/endpoints";
import { apiClient } from "../api/client";
import { RegistryModel, ChatMessage, PoolStatus, ShardPlan, ApiMessage, ContentPart } from "../api/types";
import { saveListWithTrim } from "../lib/safeStorage";
import { parseThinking, parseUserContent, buildUserContent } from "../lib/messageContent";
import { Markdown } from "../components/Markdown";
import { ThinkingBlock } from "../components/ThinkingBlock";
import { DeviceContribution } from "../components/DeviceContribution";

interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  modelId: string;
  timestamp: number;
  archived?: boolean;
}

const STORAGE_KEY = "localy_conversations";

export const ChatPage: React.FC = () => {
  const [models, setModels] = useState<RegistryModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState<boolean>(false);
  const [copiedModel, setCopiedModel] = useState<boolean>(false);

  // Message input state
  const [input, setInput] = useState<string>("");
  const [generating, setGenerating] = useState<boolean>(false);
  // Which conversation is actively streaming (so the "streaming" bubble only
  // shows on that chat, not on whatever chat you switch to mid-generation).
  const [generatingConvId, setGeneratingConvId] = useState<string | null>(null);

  // Speed statistics
  const [tokSec, setTokSec] = useState<number>(0);
  const [generatedTokens, setGeneratedTokens] = useState<number>(0);
  const [waiting, setWaiting] = useState<boolean>(false); // true until first token

  // Device pool status (for the multi-device contribution indicator)
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [poolExpanded, setPoolExpanded] = useState<boolean>(false);
  // Real per-device layer split for the currently-served pooled model.
  const [activePlan, setActivePlan] = useState<ShardPlan | null>(null);
  const plannedModelRef = useRef<string | null>(null);

  // Document attachments staged for the next message (extracted to text).
  const [attachments, setAttachments] = useState<{ name: string; text: string; truncated: boolean }[]>([]);
  const [attaching, setAttaching] = useState<boolean>(false);
  // Staged images (base64 data URLs), only usable with vision-capable models.
  const [images, setImages] = useState<{ name: string; dataUrl: string }[]>([]);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const quotaWarnedRef = useRef<boolean>(false);
  // Which model has actually produced output this session — so the "first-run
  // load can take a moment" hint only shows before a model is loaded, not on
  // every message (the model stays resident in the engine between messages).
  const loadedModelRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);

  // Load models and conversations on mount
  useEffect(() => {
    fetchModels();
    loadConversations();
    refreshPool();
    const t = setInterval(refreshPool, 8000);
    return () => {
      clearInterval(t);
      // Abort any in-flight stream when leaving the page.
      abortRef.current?.abort();
    };
  }, []);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversations, activeConvId, generating]);

  const refreshPool = async () => {
    try {
      const status = await api.getPoolStatus();
      setPool(status);
      // Fetch the true layer split once per active model (it's static for a
      // given pool+model), so the chat can show who computes what.
      if (status.pooled_active && status.active_model && status.node_count > 1) {
        if (plannedModelRef.current !== status.active_model) {
          plannedModelRef.current = status.active_model;
          try {
            setActivePlan(await api.poolFit(status.active_model));
          } catch {
            setActivePlan(null);
          }
        }
      } else {
        plannedModelRef.current = null;
        setActivePlan(null);
      }
    } catch {
      /* pool status is best-effort */
    }
  };

  // Fetch local models
  const fetchModels = async () => {
    try {
      const data = await api.getModels();
      const downloaded = data.filter((m) => m.variants.some((v) => v.is_downloaded));
      setModels(downloaded);
      if (downloaded.length > 0) {
        setSelectedModel(`${downloaded[0].id}`);
      }
    } catch (e) {
      console.error("Failed to load models:", e);
    }
  };

  // Persist conversations, trimming oldest if we hit the storage quota.
  const persist = (updated: Conversation[]) => {
    const { trimmed } = saveListWithTrim(STORAGE_KEY, updated);
    if (trimmed > 0 && !quotaWarnedRef.current) {
      quotaWarnedRef.current = true;
      console.warn(`Storage full — archived ${trimmed} oldest conversation(s) to keep recent ones.`);
    }
  };

  const loadConversations = () => {
    const data = localStorage.getItem(STORAGE_KEY);
    if (data) {
      try {
        const parsed = JSON.parse(data) as Conversation[];
        setConversations(parsed);
        const firstActive = parsed.find((c) => !c.archived);
        if (firstActive) setActiveConvId(firstActive.id);
      } catch (e) {
        console.error(e);
      }
    }
  };

  const saveConversations = (updated: Conversation[]) => {
    setConversations(updated);
    persist(updated);
  };

  // Start new conversation
  const startNewChat = () => {
    if (!selectedModel) return;
    const newConv: Conversation = {
      id: Math.random().toString(36).substring(7),
      title: `New Conversation (${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })})`,
      messages: [],
      modelId: selectedModel,
      timestamp: Date.now(),
    };
    saveConversations([newConv, ...conversations]);
    setActiveConvId(newConv.id);
    setShowArchived(false);
  };

  const getActiveConv = (): Conversation | undefined => conversations.find((c) => c.id === activeConvId);

  // --- conversation management ---------------------------------------------

  const deleteConv = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const conv = conversations.find((c) => c.id === id);
    if (conv && conv.messages.length > 0 && !window.confirm("Delete this conversation permanently?")) return;
    const updated = conversations.filter((c) => c.id !== id);
    saveConversations(updated);
    if (activeConvId === id) {
      // Pick the next chat from whichever tab is currently shown.
      const next = updated.find((c) => !!c.archived === showArchived);
      setActiveConvId(next ? next.id : null);
    }
  };

  const toggleArchive = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const updated = conversations.map((c) => (c.id === id ? { ...c, archived: !c.archived } : c));
    saveConversations(updated);
    if (activeConvId === id) {
      // The chat just left the current tab; select another from this tab.
      const next = updated.find((c) => c.id !== id && !!c.archived === showArchived);
      setActiveConvId(next ? next.id : null);
    }
  };

  const renameConv = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const conv = conversations.find((c) => c.id === id);
    const title = window.prompt("Rename conversation", conv?.title || "");
    if (title == null) return;
    saveConversations(conversations.map((c) => (c.id === id ? { ...c, title: title.trim() || c.title } : c)));
  };

  const copyModelName = () => {
    if (!selectedModel) return;
    navigator.clipboard?.writeText(selectedModel).then(() => {
      setCopiedModel(true);
      setTimeout(() => setCopiedModel(false), 1500);
    });
  };

  const stopGeneration = () => {
    abortRef.current?.abort();
  };

  // --- document attachments -------------------------------------------------

  const onPickFiles = () => fileInputRef.current?.click();

  const handleFilesSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = ""; // allow re-picking the same file
    if (files.length === 0) return;
    setAttaching(true);
    for (const f of files) {
      try {
        const res = await api.extractDocument(f);
        if (res.error) {
          alert(`Couldn't read ${f.name}: ${res.error}`);
          continue;
        }
        if (!res.text.trim()) {
          alert(`No readable text found in ${f.name}.`);
          continue;
        }
        setAttachments((prev) => [...prev, { name: res.filename, text: res.text, truncated: res.truncated }]);
      } catch (err: any) {
        alert(`Couldn't attach ${f.name}: ${err.message}`);
      }
    }
    setAttaching(false);
  };

  const removeAttachment = (idx: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  };

  // --- image attachments (vision models only) -------------------------------

  const onPickImages = () => imageInputRef.current?.click();

  const handleImagesSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    files.forEach((f) => {
      const reader = new FileReader();
      reader.onload = () => {
        const url = String(reader.result || "");
        if (url) setImages((prev) => [...prev, { name: f.name, dataUrl: url }]);
      };
      reader.readAsDataURL(f); // -> data:image/...;base64,...
    });
  };

  const removeImage = (idx: number) => setImages((prev) => prev.filter((_, i) => i !== idx));

  // Send message
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && attachments.length === 0 && images.length === 0) || generating || !activeConvId || !selectedModel) return;

    const convId = activeConvId;
    const activeConv = getActiveConv();
    if (!activeConv) return;

    // Stored/displayed content: typed text + file/image chips (image data is
    // NOT persisted — too large for localStorage and only needed this turn).
    const content = buildUserContent(input, attachments, images.map((im) => im.name));
    const userMsg: ChatMessage = { role: "user", content };
    const baseMessages = [...activeConv.messages, userMsg];
    const assistantIndex = baseMessages.length;

    // What we actually send to the model. For vision models with staged images,
    // the current turn is sent as OpenAI multimodal parts (text + image_url).
    const sendImages = images.slice();
    const apiMessages: ApiMessage[] = baseMessages.map((m) => ({ role: m.role, content: m.content }));
    if (sendImages.length > 0) {
      // Text part = typed text + any document context, but NOT the image-name
      // markers; fall back to a default prompt when only images were attached.
      const textForModel = attachments.length ? buildUserContent(input, attachments, []) : input;
      const parts: ContentPart[] = [{ type: "text", text: textForModel.trim() || "Describe the image(s)." }];
      sendImages.forEach((im) => parts.push({ type: "image_url", image_url: { url: im.dataUrl } }));
      apiMessages[apiMessages.length - 1] = { role: "user", content: parts };
    }

    const isFirst = activeConv.messages.length === 0;
    const titleSource = input.trim() || (attachments[0]?.name) || (images[0]?.name) || "New chat";
    const title = isFirst ? titleSource.slice(0, 30) + (titleSource.length > 30 ? "…" : "") : activeConv.title;

    setConversations((prev) => {
      const next = prev.map((c) =>
        c.id === convId
          ? { ...c, title, modelId: selectedModel, messages: [...baseMessages, { role: "assistant", content: "" } as ChatMessage] }
          : c
      );
      persist(next);
      return next;
    });

    setInput("");
    setAttachments([]);
    setImages([]);
    setGenerating(true);
    setGeneratingConvId(convId);
    setWaiting(true);
    setGeneratedTokens(0);
    setTokSec(0);

    let acc = "";
    let tokenCount = 0;
    const startTime = Date.now();

    const setAssistant = (content: string, doPersist = false) => {
      setConversations((prev) => {
        const next = prev.map((c) => {
          if (c.id !== convId) return c;
          const msgs = [...c.messages];
          if (msgs[assistantIndex]) msgs[assistantIndex] = { role: "assistant", content };
          return { ...c, messages: msgs };
        });
        if (doPersist) persist(next);
        return next;
      });
    };

    const controller = new AbortController();
    abortRef.current = controller;

    await apiClient.streamChat(
      { model: selectedModel, messages: apiMessages, temperature: 0.7 },
      (token) => {
        setWaiting(false);
        // First token proves this model is now loaded and resident.
        loadedModelRef.current = selectedModel;
        acc += token;
        tokenCount++;
        setGeneratedTokens(tokenCount);
        const elapsed = (Date.now() - startTime) / 1000;
        if (elapsed > 0) setTokSec(tokenCount / elapsed);
        setAssistant(acc);
      },
      () => {
        setGenerating(false);
        setGeneratingConvId(null);
        setWaiting(false);
        setAssistant(acc, true);
        abortRef.current = null;
      },
      (err) => {
        setGenerating(false);
        setGeneratingConvId(null);
        setWaiting(false);
        setAssistant(acc || `⚠ ${err.message}`, true);
        abortRef.current = null;
      },
      controller.signal
    );
  };

  const activeConv = getActiveConv();
  const activeList = conversations.filter((c) => !c.archived);
  const archivedList = conversations.filter((c) => c.archived);
  const visibleList = showArchived ? archivedList : activeList;

  // Device pool: is more than one device contributing?
  const multiDevice = !!pool && pool.pooled_active && pool.node_count > 1;

  // Does the selected model accept images?
  const visionModel = models.find((m) => m.id === selectedModel)?.supports_vision === true;

  return (
    <div style={styles.chatWrapper}>
      {/* Sidebar: Chats List */}
      <div style={styles.sidebar} className="glass-panel">
        <button className="btn btn-primary" style={styles.newChatBtn} onClick={startNewChat}>
          + New Chat
        </button>

        <div style={styles.tabRow}>
          <button
            style={{ ...styles.tabBtn, ...(showArchived ? {} : styles.tabActive) }}
            onClick={() => setShowArchived(false)}
          >
            Active ({activeList.length})
          </button>
          <button
            style={{ ...styles.tabBtn, ...(showArchived ? styles.tabActive : {}) }}
            onClick={() => setShowArchived(true)}
          >
            Archived ({archivedList.length})
          </button>
        </div>

        <div style={styles.convList}>
          {visibleList.length === 0 ? (
            <p style={styles.emptySidebar}>{showArchived ? "No archived chats." : "No conversations yet."}</p>
          ) : (
            visibleList.map((c) => (
              <div
                key={c.id}
                onClick={() => setActiveConvId(c.id)}
                className="conv-item"
                style={{
                  ...styles.convItem,
                  background: c.id === activeConvId ? "rgba(99, 102, 241, 0.12)" : "transparent",
                  borderColor: c.id === activeConvId ? "rgba(99, 102, 241, 0.3)" : "transparent",
                }}
              >
                <div style={styles.convItemMain}>
                  <div style={styles.convItemTitle}>{c.title}</div>
                  <div style={styles.convItemSub}>{c.modelId}</div>
                </div>
                <div style={styles.convActions}>
                  <button title="Rename" style={styles.iconBtn} onClick={(e) => renameConv(c.id, e)}>✎</button>
                  <button
                    title={c.archived ? "Unarchive" : "Archive"}
                    style={styles.iconBtn}
                    onClick={(e) => toggleArchive(c.id, e)}
                  >
                    {c.archived ? "⇤" : "🗄"}
                  </button>
                  <button title="Delete" style={styles.iconBtn} onClick={(e) => deleteConv(c.id, e)}>🗑</button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Chat Feed */}
      <div style={styles.feedWrapper}>
        {/* Top Header Panel */}
        <div style={styles.header} className="glass-panel">
          <div style={styles.headerTitle}>
            <span>Conversational Chat</span>
            {generating && (
              <span style={styles.liveStat} className="pulse-indicator">
                ⚡ {tokSec.toFixed(1)} tok/s ({generatedTokens} tokens)
              </span>
            )}
            {multiDevice && (
              <span
                style={styles.deviceBadge}
                onClick={() => setPoolExpanded((v) => !v)}
                title="This response is computed across multiple devices"
              >
                🔗 {pool!.node_count} devices
              </span>
            )}
          </div>

          <div style={styles.modelSelectorWrapper}>
            <span style={styles.selectorLabel}>Active Model:</span>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={generating}
              style={styles.modelSelect}
            >
              {models.length === 0 ? (
                <option value="">No models downloaded</option>
              ) : (
                models.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))
              )}
            </select>
            <button
              type="button"
              title="Copy model name"
              onClick={copyModelName}
              disabled={!selectedModel}
              style={styles.copyModelBtn}
            >
              {copiedModel ? "✓" : "⧉"}
            </button>
          </div>
        </div>

        {/* Multi-device contribution detail (real layer split) */}
        {multiDevice && poolExpanded && activePlan && (
          <div className="glass-panel">
            <DeviceContribution plan={activePlan} status={pool} compact />
          </div>
        )}

        {/* Chat History Panel */}
        <div style={styles.messageArea}>
          {!activeConv ? (
            <div style={styles.emptyState}>
              <div style={styles.emptyIcon}>💬</div>
              <h2>Select a Conversation to Start Chatting</h2>
              <p>Or click "+ New Chat" in the sidebar to load the optimizer config.</p>
            </div>
          ) : activeConv.messages.length === 0 ? (
            <div style={styles.emptyState}>
              <div style={styles.emptyIcon}>🤖</div>
              <h2>Localy Server Ready</h2>
              <p>Type a message below. Localy will automatically tune threads and compute fits.</p>
            </div>
          ) : (
            <div style={styles.messageList}>
              {activeConv.messages.map((msg, idx) => {
                const isUser = msg.role === "user";
                const isStreaming =
                  !isUser && generating && generatingConvId === activeConv.id && idx === activeConv.messages.length - 1;
                const parsed = isUser ? null : parseThinking(msg.content);

                return (
                  <div
                    key={idx}
                    style={{ ...styles.messageRow, justifyContent: isUser ? "flex-end" : "flex-start" }}
                  >
                    <div
                      className={isStreaming ? "cursor-blink glass-panel" : isUser ? "" : "glass-panel"}
                      style={{
                        ...styles.messageBubble,
                        background: isUser ? "var(--primary)" : "var(--panel-bg)",
                        border: isUser ? "none" : "1px solid var(--panel-border)",
                      }}
                    >
                      <div style={styles.messageSender}>
                        {isUser ? "You" : `Assistant (${activeConv.modelId})`}
                      </div>
                      <div style={styles.messageText}>
                        {isStreaming && !msg.content ? (
                          <span style={styles.thinking} className="pulse-indicator">
                            {waiting
                              ? (loadedModelRef.current === activeConv.modelId ||
                                 (pool?.pooled_active && pool?.active_model === activeConv.modelId)
                                  ? "Thinking…"
                                  : "Loading model (first run can take a moment)…")
                              : "Generating…"}
                          </span>
                        ) : isUser ? (
                          (() => {
                            const parsed = parseUserContent(msg.content);
                            return (
                              <>
                                {parsed.files.length > 0 && (
                                  <div style={styles.attachChipRow}>
                                    {parsed.files.map((f, i) => (
                                      <span key={i} style={styles.attachChipSent}>📎 {f}</span>
                                    ))}
                                  </div>
                                )}
                                {parsed.text && <span style={{ whiteSpace: "pre-wrap" }}>{parsed.text}</span>}
                              </>
                            );
                          })()
                        ) : (
                          <>
                            {parsed!.thinking && (
                              <ThinkingBlock thinking={parsed!.thinking} inProgress={parsed!.thinkingInProgress} />
                            )}
                            {parsed!.answer ? (
                              <Markdown text={parsed!.answer} />
                            ) : parsed!.thinkingInProgress ? (
                              <span style={styles.thinking} className="pulse-indicator">Reasoning…</span>
                            ) : null}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input Text Form */}
        <div style={styles.inputArea} className="glass-panel">
          {/* Staged attachments */}
          {(attachments.length > 0 || attaching) && (
            <div style={styles.stagedRow}>
              {attachments.map((a, i) => (
                <span key={i} style={styles.stagedChip}>
                  📎 {a.name}
                  {a.truncated && <span style={styles.truncTag} title="Truncated to fit context"> (trimmed)</span>}
                  <button type="button" style={styles.chipX} onClick={() => removeAttachment(i)}>×</button>
                </span>
              ))}
              {attaching && <span style={styles.stagedChipMuted}>Extracting…</span>}
            </div>
          )}
          {/* Staged images (thumbnails) */}
          {images.length > 0 && (
            <div style={styles.stagedRow}>
              {images.map((im, i) => (
                <span key={i} style={styles.imageChip}>
                  <img src={im.dataUrl} alt={im.name} style={styles.thumb} />
                  <button type="button" style={styles.chipX} onClick={() => removeImage(i)}>×</button>
                </span>
              ))}
            </div>
          )}
          <form style={styles.inputForm} onSubmit={handleSendMessage}>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".txt,.md,.markdown,.pdf,.json,.csv,.log,.py,.js,.ts,.tsx,.jsx,.java,.kt,.go,.rs,.c,.cpp,.h,.cs,.rb,.php,.sh,.yaml,.yml,.toml,.xml,.html,.css"
              style={{ display: "none" }}
              onChange={handleFilesSelected}
            />
            <input
              ref={imageInputRef}
              type="file"
              multiple
              accept="image/*"
              style={{ display: "none" }}
              onChange={handleImagesSelected}
            />
            <button
              type="button"
              title="Attach a document (PDF, text, code) as context"
              onClick={onPickFiles}
              disabled={generating || !activeConvId || attaching}
              style={styles.attachBtn}
            >
              📎
            </button>
            {visionModel && (
              <button
                type="button"
                title="Attach an image (this model supports vision)"
                onClick={onPickImages}
                disabled={generating || !activeConvId}
                style={styles.attachBtn}
              >
                🖼
              </button>
            )}
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={generating || !activeConvId}
              placeholder={activeConvId ? "Ask a question..." : "Select or start a chat first..."}
              style={styles.textInput}
            />
            {generating ? (
              <button type="button" className="btn" onClick={stopGeneration} style={styles.stopBtn}>
                ■ Stop
              </button>
            ) : (
              <button
                type="submit"
                className="btn btn-primary"
                disabled={(!input.trim() && attachments.length === 0 && images.length === 0) || !activeConvId}
                style={styles.sendBtn}
              >
                Send
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  chatWrapper: {
    display: "flex",
    flexDirection: "row",
    height: "100%",
    width: "100%",
    minWidth: 0,
    overflow: "hidden",
    background: "#09090b",
  },
  sidebar: {
    width: "280px",
    height: "100%",
    borderRight: "1px solid var(--panel-border)",
    display: "flex",
    flexDirection: "column",
    padding: "20px",
    background: "rgba(10, 10, 15, 0.4)",
    flexShrink: 0,
  },
  newChatBtn: { width: "100%", padding: "12px", marginBottom: "14px", fontWeight: "600" },
  tabRow: { display: "flex", gap: "6px", marginBottom: "14px" },
  tabBtn: {
    flex: 1,
    padding: "6px 8px",
    fontSize: "12px",
    color: "#a1a1aa",
    background: "transparent",
    border: "1px solid var(--panel-border)",
    borderRadius: "6px",
    cursor: "pointer",
  },
  tabActive: { background: "rgba(99, 102, 241, 0.15)", color: "#fff", borderColor: "rgba(99,102,241,0.3)" },
  convList: { flexGrow: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "8px" },
  emptySidebar: { color: "#71717a", fontSize: "13px", textAlign: "center", marginTop: "20px" },
  convItem: {
    padding: "10px 12px",
    borderRadius: "8px",
    border: "1px solid transparent",
    cursor: "pointer",
    transition: "all 0.15s ease-out",
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  convItemMain: { minWidth: 0, flexGrow: 1 },
  convItemTitle: {
    fontSize: "13px",
    fontWeight: "500",
    color: "#e4e4e7",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  convItemSub: { fontSize: "11px", color: "#71717a", marginTop: "4px" },
  convActions: { display: "flex", gap: "2px", flexShrink: 0 },
  iconBtn: {
    background: "transparent",
    border: "none",
    color: "#71717a",
    cursor: "pointer",
    fontSize: "12px",
    padding: "2px 4px",
    borderRadius: "4px",
    lineHeight: 1,
  },
  feedWrapper: {
    display: "flex",
    flexDirection: "column",
    flexGrow: 1,
    minWidth: 0,
    height: "100%",
    position: "relative",
  },
  header: {
    minHeight: "64px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 24px",
    borderBottom: "1px solid var(--panel-border)",
    background: "rgba(10, 10, 15, 0.3)",
  },
  headerTitle: {
    fontSize: "16px",
    fontWeight: "600",
    color: "#fff",
    display: "flex",
    alignItems: "center",
    gap: "12px",
  },
  liveStat: {
    fontSize: "12px",
    background: "rgba(99, 102, 241, 0.15)",
    border: "1px solid rgba(99, 102, 241, 0.3)",
    borderRadius: "4px",
    color: "#818cf8",
    padding: "3px 8px",
  },
  deviceBadge: {
    fontSize: "12px",
    background: "rgba(34, 197, 94, 0.15)",
    border: "1px solid rgba(34, 197, 94, 0.35)",
    borderRadius: "4px",
    color: "#4ade80",
    padding: "3px 8px",
    cursor: "pointer",
  },
  modelSelectorWrapper: { display: "flex", alignItems: "center", gap: "8px" },
  selectorLabel: { fontSize: "12px", color: "#71717a" },
  modelSelect: { padding: "6px 12px", fontSize: "13px", minWidth: "160px" },
  copyModelBtn: {
    padding: "6px 10px",
    fontSize: "13px",
    background: "transparent",
    color: "#a1a1aa",
    border: "1px solid var(--panel-border)",
    borderRadius: "6px",
    cursor: "pointer",
  },
  messageArea: { flexGrow: 1, overflowY: "auto", padding: "30px 24px", display: "flex", flexDirection: "column" },
  emptyState: { margin: "auto", textAlign: "center", maxWidth: "360px" },
  emptyIcon: { fontSize: "48px", marginBottom: "16px" },
  messageList: { display: "flex", flexDirection: "column", gap: "20px", width: "100%", maxWidth: "800px", margin: "0 auto" },
  messageRow: { display: "flex", width: "100%" },
  messageBubble: { maxWidth: "85%", borderRadius: "12px", padding: "16px 20px", boxShadow: "0 4px 12px rgba(0,0,0,0.15)" },
  messageSender: { fontSize: "11px", color: "#71717a", marginBottom: "6px", fontWeight: "600", textTransform: "uppercase" },
  thinking: { fontSize: "14px", color: "#a1a1aa", fontStyle: "italic" },
  messageText: { fontSize: "14px", color: "#f4f4f5", lineHeight: "1.6" },
  inputArea: { padding: "20px 24px", background: "rgba(10, 10, 15, 0.4)", borderTop: "1px solid var(--panel-border)" },
  stagedRow: { display: "flex", flexWrap: "wrap", gap: "8px", maxWidth: "800px", margin: "0 auto 10px" },
  stagedChip: { display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "12px", color: "#c7d2fe", background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.35)", borderRadius: "6px", padding: "3px 8px" },
  stagedChipMuted: { fontSize: "12px", color: "#a1a1aa", fontStyle: "italic", alignSelf: "center" },
  truncTag: { color: "#fbbf24" },
  chipX: { background: "transparent", border: "none", color: "#a5b4fc", cursor: "pointer", fontSize: "14px", lineHeight: 1, padding: "0 0 0 2px" },
  imageChip: { position: "relative", display: "inline-flex", alignItems: "center" },
  thumb: { width: "48px", height: "48px", objectFit: "cover", borderRadius: "6px", border: "1px solid var(--panel-border)" },
  attachChipRow: { display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "6px" },
  attachChipSent: { fontSize: "11px", color: "#e0e7ff", background: "rgba(255,255,255,0.12)", borderRadius: "5px", padding: "2px 7px" },
  attachBtn: { padding: "0 14px", fontSize: "18px", background: "transparent", color: "#a1a1aa", border: "1px solid var(--panel-border)", borderRadius: "8px", cursor: "pointer" },
  inputForm: { display: "flex", gap: "12px", width: "100%", maxWidth: "800px", margin: "0 auto" },
  textInput: { flexGrow: 1, padding: "12px 16px", fontSize: "14px" },
  sendBtn: { padding: "0 24px", fontSize: "14px" },
  stopBtn: {
    padding: "0 24px",
    fontSize: "14px",
    background: "rgba(239, 68, 68, 0.15)",
    border: "1px solid rgba(239, 68, 68, 0.4)",
    color: "#f87171",
  },
};
