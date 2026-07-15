import React, { useState, useEffect, useRef } from "react";
import { api } from "../api/endpoints";
import { apiClient } from "../api/client";
import { RegistryModel, ChatMessage } from "../api/types";

interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  modelId: string;
  timestamp: number;
}

export const ChatPage: React.FC = () => {
  const [models, setModels] = useState<RegistryModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  
  // Message input state
  const [input, setInput] = useState<string>("");
  const [generating, setGenerating] = useState<boolean>(false);
  
  // Speed statistics
  const [tokSec, setTokSec] = useState<number>(0);
  const [generatedTokens, setGeneratedTokens] = useState<number>(0);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Load models and conversations on mount
  useEffect(() => {
    fetchModels();
    loadConversations();
  }, []);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversations, activeConvId, generating]);

  // Fetch local models
  const fetchModels = async () => {
    try {
      const data = await api.getModels();
      // Filter only downloaded models
      const downloaded = data.filter(m => m.variants.some(v => v.is_downloaded));
      setModels(downloaded);
      
      // Auto-select first model
      if (downloaded.length > 0) {
        // Find variant tag
        const firstModel = downloaded[0];
        const downloadedVar = firstModel.variants.find(v => v.is_downloaded);
        if (downloadedVar) {
          setSelectedModel(`${firstModel.id}`);
        }
      }
    } catch (e) {
      console.error("Failed to load models:", e);
    }
  };

  // Load conversations from local storage
  const loadConversations = () => {
    const data = localStorage.getItem("localy_conversations");
    if (data) {
      try {
        const parsed = JSON.parse(data) as Conversation[];
        setConversations(parsed);
        if (parsed.length > 0) {
          setActiveConvId(parsed[0].id);
        }
      } catch (e) {
        console.error(e);
      }
    }
  };

  // Save conversations helper
  const saveConversations = (updated: Conversation[]) => {
    setConversations(updated);
    localStorage.setItem("localy_conversations", JSON.stringify(updated));
  };

  // Start new conversation
  const startNewChat = () => {
    if (!selectedModel) return;
    const newConv: Conversation = {
      id: Math.random().toString(36).substring(7),
      title: `New Conversation (${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})})`,
      messages: [],
      modelId: selectedModel,
      timestamp: Date.now()
    };
    saveConversations([newConv, ...conversations]);
    setActiveConvId(newConv.id);
  };

  // Get active conversation
  const getActiveConv = (): Conversation | undefined => {
    return conversations.find(c => c.id === activeConvId);
  };

  // Send message
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || generating || !activeConvId || !selectedModel) return;

    const userMsg: ChatMessage = { role: "user", content: input };
    const activeConv = getActiveConv();
    if (!activeConv) return;

    const updatedMessages = [...activeConv.messages, userMsg];
    
    // Update active conversation title if empty
    let title = activeConv.title;
    if (activeConv.messages.length === 0) {
      title = input.slice(0, 30) + (input.length > 30 ? "..." : "");
    }

    const updatedConv = {
      ...activeConv,
      title,
      messages: updatedMessages,
      modelId: selectedModel
    };

    const nextConversations = conversations.map(c => c.id === activeConvId ? updatedConv : c);
    saveConversations(nextConversations);
    setInput("");
    
    // Set up generating variables
    setGenerating(true);
    setGeneratedTokens(0);
    setTokSec(0);
    
    let tokenCount = 0;
    const startTime = Date.now();

    // Prepare helper logic to update streaming assistant message
    const assistantMsgIndex = updatedMessages.length;
    const initialAssistantMsg: ChatMessage = { role: "assistant", content: "" };
    
    const streamingConv = {
      ...updatedConv,
      messages: [...updatedMessages, initialAssistantMsg]
    };
    
    setConversations(conversations.map(c => c.id === activeConvId ? streamingConv : c));

    // Call SSE API streaming
    await apiClient.streamChat(
      {
        model: selectedModel,
        messages: updatedMessages,
        temperature: 0.7,
      },
      (token) => {
        tokenCount++;
        setGeneratedTokens(tokenCount);
        
        // Calculate dynamic tokens/sec
        const elapsed = (Date.now() - startTime) / 1000;
        if (elapsed > 0) {
          setTokSec(tokenCount / elapsed);
        }

        // Append token
        streamingConv.messages[assistantMsgIndex].content += token;
        setConversations(conversations.map(c => c.id === activeConvId ? { ...streamingConv } : c));
      },
      () => {
        // Stream completed
        setGenerating(false);
        saveConversations(conversations.map(c => c.id === activeConvId ? streamingConv : c));
      },
      (err) => {
        setGenerating(false);
        streamingConv.messages[assistantMsgIndex].content = `Error: ${err.message}`;
        saveConversations(conversations.map(c => c.id === activeConvId ? streamingConv : c));
      }
    );
  };

  // Simple Markdown Code highlight helper
  const renderMessageContent = (text: string) => {
    const parts = text.split(/(```[\s\S]*?```)/g);
    return parts.map((part, idx) => {
      if (part.startsWith("```")) {
        const lines = part.split("\n");
        const code = lines.slice(1, -1).join("\n");
        return (
          <pre key={idx} style={styles.codeBlock}>
            <code>{code}</code>
          </pre>
        );
      }
      return <span key={idx} style={{ whiteSpace: "pre-wrap" }}>{part}</span>;
    });
  };

  const activeConv = getActiveConv();

  return (
    <div style={styles.chatWrapper}>
      
      {/* Sidebar: Chats List */}
      <div style={styles.sidebar} className="glass-panel">
        <button className="btn btn-primary" style={styles.newChatBtn} onClick={startNewChat}>
          + New Chat
        </button>
        
        <div style={styles.convList}>
          {conversations.length === 0 ? (
            <p style={styles.emptySidebar}>No conversations yet.</p>
          ) : (
            conversations.map(c => (
              <div
                key={c.id}
                onClick={() => setActiveConvId(c.id)}
                style={{
                  ...styles.convItem,
                  background: c.id === activeConvId ? "rgba(99, 102, 241, 0.12)" : "transparent",
                  borderColor: c.id === activeConvId ? "rgba(99, 102, 241, 0.3)" : "transparent"
                }}
              >
                <div style={styles.convItemTitle}>{c.title}</div>
                <div style={styles.convItemSub}>{c.modelId}</div>
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
                models.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))
              )}
            </select>
          </div>
        </div>

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
                const isStreaming = !isUser && generating && idx === activeConv.messages.length - 1;
                
                return (
                  <div
                    key={idx}
                    style={{
                      ...styles.messageRow,
                      justifyContent: isUser ? "flex-end" : "flex-start"
                    }}
                  >
                    <div
                      className={isStreaming ? "cursor-blink glass-panel" : (isUser ? "" : "glass-panel")}
                      style={{
                        ...styles.messageBubble,
                        background: isUser ? "var(--primary)" : "var(--panel-bg)",
                        border: isUser ? "none" : "1px solid var(--panel-border)"
                      }}
                    >
                      <div style={styles.messageSender}>
                        {isUser ? "You" : `Assistant (${activeConv.modelId})`}
                      </div>
                      <div style={styles.messageText}>
                        {renderMessageContent(msg.content)}
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
          <form style={styles.inputForm} onSubmit={handleSendMessage}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={generating || !activeConvId}
              placeholder={activeConvId ? "Ask a question..." : "Select or start a chat first..."}
              style={styles.textInput}
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={generating || !input.trim() || !activeConvId}
              style={styles.sendBtn}
            >
              Send
            </button>
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
    background: "#09090b"
  },
  sidebar: {
    width: "280px",
    height: "100%",
    borderRight: "1px solid var(--panel-border)",
    display: "flex",
    flexDirection: "column",
    padding: "20px",
    background: "rgba(10, 10, 15, 0.4)",
    flexShrink: 0
  },
  newChatBtn: {
    width: "100%",
    padding: "12px",
    marginBottom: "20px",
    fontWeight: "600"
  },
  convList: {
    flexGrow: 1,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: "8px"
  },
  emptySidebar: {
    color: "#71717a",
    fontSize: "13px",
    textAlign: "center",
    marginTop: "20px"
  },
  convItem: {
    padding: "12px",
    borderRadius: "8px",
    border: "1px solid transparent",
    cursor: "pointer",
    transition: "all 0.15s ease-out"
  },
  convItemTitle: {
    fontSize: "13px",
    fontWeight: "500",
    color: "#e4e4e7",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis"
  },
  convItemSub: {
    fontSize: "11px",
    color: "#71717a",
    marginTop: "4px"
  },
  feedWrapper: {
    display: "flex",
    flexDirection: "column",
    flexGrow: 1,
    minWidth: 0,
    height: "100%",
    position: "relative"
  },
  header: {
    height: "64px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 24px",
    borderBottom: "1px solid var(--panel-border)",
    background: "rgba(10, 10, 15, 0.3)"
  },
  headerTitle: {
    fontSize: "16px",
    fontWeight: "600",
    color: "#fff",
    display: "flex",
    alignItems: "center",
    gap: "12px"
  },
  liveStat: {
    fontSize: "12px",
    background: "rgba(99, 102, 241, 0.15)",
    border: "1px solid rgba(99, 102, 241, 0.3)",
    borderRadius: "4px",
    color: "#818cf8",
    padding: "3px 8px"
  },
  modelSelectorWrapper: {
    display: "flex",
    alignItems: "center",
    gap: "8px"
  },
  selectorLabel: {
    fontSize: "12px",
    color: "#71717a"
  },
  modelSelect: {
    padding: "6px 12px",
    fontSize: "13px",
    minWidth: "160px"
  },
  messageArea: {
    flexGrow: 1,
    overflowY: "auto",
    padding: "30px 24px",
    display: "flex",
    flexDirection: "column"
  },
  emptyState: {
    margin: "auto",
    textAlign: "center",
    maxWidth: "360px"
  },
  emptyIcon: {
    fontSize: "48px",
    marginBottom: "16px"
  },
  messageList: {
    display: "flex",
    flexDirection: "column",
    gap: "20px",
    width: "100%",
    maxWidth: "800px",
    margin: "0 auto"
  },
  messageRow: {
    display: "flex",
    width: "100%"
  },
  messageBubble: {
    maxWidth: "85%",
    borderRadius: "12px",
    padding: "16px 20px",
    boxShadow: "0 4px 12px rgba(0,0,0,0.15)"
  },
  messageSender: {
    fontSize: "11px",
    color: "#71717a",
    marginBottom: "6px",
    fontWeight: "600",
    textTransform: "uppercase"
  },
  messageText: {
    fontSize: "14px",
    color: "#f4f4f5",
    lineHeight: "1.6"
  },
  codeBlock: {
    marginTop: "12px",
    marginBottom: "12px"
  },
  inputArea: {
    padding: "20px 24px",
    background: "rgba(10, 10, 15, 0.4)",
    borderTop: "1px solid var(--panel-border)"
  },
  inputForm: {
    display: "flex",
    gap: "12px",
    width: "100%",
    maxWidth: "800px",
    margin: "0 auto"
  },
  textInput: {
    flexGrow: 1,
    padding: "12px 16px",
    fontSize: "14px"
  },
  sendBtn: {
    padding: "0 24px",
    fontSize: "14px"
  }
};
