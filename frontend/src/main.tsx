import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { api, ApiError, type Models } from "./api";
import { SignIn } from "./features/signin";
import { Button } from "./ui";
import "./styles.css";

const Workspace = lazy(() => import("./workspace"));
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });

function App() {
  const session = useQuery({ queryKey: ["session"], queryFn: ({ signal }) => api<Models["SessionInfo"]>("/me", { signal }) });
  if (session.isPending || (session.error instanceof ApiError && session.error.status === 401)) {
    return <SignIn checkingSession={session.isPending} />;
  }
  if (!session.data) return <main className="entry"><p role="alert">No se pudo conectar con la API.</p>
    <Button onClick={() => { void session.refetch(); }}>Reintentar</Button></main>;
  return <Suspense fallback={<main className="entry" role="status">Cargando el espacio…</main>}>
    <Workspace key={session.data.user_id} session={session.data} />
  </Suspense>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><QueryClientProvider client={queryClient}><App /></QueryClientProvider></StrictMode>,
);
