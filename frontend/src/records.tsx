import { ClipboardList, Search } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button, Card } from "./ui";

const statusLabels: Record<string, string> = {
  active: "Activo", archived: "Archivado", draft: "Borrador", scheduled: "Programada",
  expired: "Vencida", revoked: "Revocada", reviewed: "Revisado", blocked: "Bloqueado",
  pending: "Pendiente", approved: "Aprobado", ready: "Listo para avanzar", processing: "En curso",
  awaiting_review: "En espera de revisión", completed: "Paso confirmado", failed: "Fallido", cancelled: "Cancelado",
  published: "Publicado",
};

export function statusLabel(state: string) {
  return statusLabels[state] ?? state;
}

export function Status({ state }: { state: string }) {
  return <span className="status-pill" data-state={state}>{statusLabel(state)}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><ClipboardList size={22} aria-hidden /><p>{children}</p></div>;
}

export function Records<T>({ title, items, columns, cells, more, empty, search }: {
  title: string; items: T[]; columns: string[]; cells: (row: T) => { key: string; values: ReactNode[] };
  more?: () => void; empty: string; search?: (row: T) => string;
}) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLocaleLowerCase("es");
  const visible = search && needle ? items.filter((item) => search(item).toLocaleLowerCase("es").includes(needle)) : items;
  return <Card>
    <div className="card-head"><h2>{title}</h2>
      {search && items.length > 0 && <label className="table-search">
        <Search size={16} aria-hidden />
        <input type="search" aria-label={"Filtrar " + title.toLocaleLowerCase("es")}
          placeholder="Filtrar registros cargados" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>}
    </div>
    {needle && <p className="filter-count" role="status">{visible.length} de {items.length} registros cargados</p>}
    {visible.length ? <div className="table-wrap" role="region" tabIndex={0} aria-label={"Tabla de " + title.toLocaleLowerCase("es")}>
      <table aria-label={title}>
        <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>{visible.map((row) => {
          const item = cells(row);
          return <tr key={item.key}>{item.values.map((value, index) => <td key={columns[index]}>{value}</td>)}</tr>;
        })}</tbody>
      </table>
    </div> : <Empty>{needle ? "Ningún registro cargado coincide con el filtro." : empty}</Empty>}
    {more && <div className="card-footer"><Button onClick={more}>Cargar más</Button></div>}
  </Card>;
}
