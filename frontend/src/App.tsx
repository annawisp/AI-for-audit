import { useEffect, useState } from "react";

type ServiceState = "checking" | "online" | "offline";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function App() {
  const [serviceState, setServiceState] = useState<ServiceState>("checking");

  useEffect(() => {
    fetch(`${apiBaseUrl}/health`)
      .then((response) => {
        if (!response.ok) throw new Error("Health check failed");
        setServiceState("online");
      })
      .catch(() => setServiceState("offline"));
  }, []);

  const statusLabel = {
    checking: "正在检查后端",
    online: "后端已连接",
    offline: "后端未连接",
  }[serviceState];

  return (
    <main>
      <section className="panel">
        <p className="eyebrow">REVENUE AUDIT · FOUNDATION</p>
        <h1>收入循环智能审计助手</h1>
        <p className="lead">
          当前已完成 Stage 1 / Step 1.1 工程底座。后续审计能力将以程序编排、证据追溯和人工复核为核心。
        </p>
        <div className={`status ${serviceState}`}>
          <span aria-hidden="true" />
          {statusLabel}
        </div>
      </section>
    </main>
  );
}

