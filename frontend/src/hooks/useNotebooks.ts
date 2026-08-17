import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createNotebook,
  deleteNotebook,
  listNotebooks,
  renameNotebook,
  setNotebookGoal,
  type GoalType,
  type NotebookRecord,
} from "../lib/api";

function nextUntitledName(notebooks: NotebookRecord[]): string {
  const usedNumbers = new Set<number>();
  for (const notebook of notebooks) {
    if (notebook.name === "Untitled") {
      usedNumbers.add(0);
      continue;
    }
    const match = /^Untitled (\d+)$/.exec(notebook.name);
    if (match) usedNumbers.add(Number(match[1]));
  }
  let n = 0;
  while (usedNumbers.has(n)) n++;
  return n === 0 ? "Untitled" : `Untitled ${n}`;
}

export function useNotebooks() {
  const [notebooks, setNotebooks] = useState<NotebookRecord[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const fetched = await listNotebooks();
      setNotebooks(fetched);
      setError(null);
      // Never auto-opens a notebook — the home gallery is the default
      // landing view. Only keeps the current selection if it's still valid
      // (e.g. after a rename), otherwise falls back to the gallery rather
      // than silently jumping into whichever notebook happens to be first.
      setActiveId((current) => (current !== null && fetched.some((n) => n.id === current) ? current : null));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addNotebook = useCallback(async () => {
    const notebook = await createNotebook(nextUntitledName(notebooks));
    setNotebooks((prev) => [notebook, ...prev]);
    setActiveId(notebook.id);
    return notebook;
  }, [notebooks]);

  const removeNotebook = useCallback(async (id: string) => {
    await deleteNotebook(id);
    setNotebooks((prev) => prev.filter((n) => n.id !== id));
    // Belt-and-suspenders, not normally hit: delete is only triggered from
    // a NotebookCard on the Home gallery, and opening a notebook always
    // routes away from Home first, so `current === id` shouldn't be
    // reachable in the primary flow today. Kept in case a future surface
    // (e.g. an in-workspace delete action) lets a notebook delete itself
    // while active.
    setActiveId((current) => (current === id ? null : current));
  }, []);

  const renameActiveNotebook = useCallback(async (id: string, name: string) => {
    const updated = await renameNotebook(id, name);
    setNotebooks((prev) => prev.map((n) => (n.id === id ? updated : n)));
    return updated;
  }, []);

  const updateGoal = useCallback(
    async (id: string, goalType: GoalType, goalDescription?: string) => {
      const updated = await setNotebookGoal(id, goalType, goalDescription);
      setNotebooks((prev) => prev.map((n) => (n.id === id ? updated : n)));
      return updated;
    },
    [],
  );

  const activeNotebook = notebooks.find((n) => n.id === activeId) ?? null;

  return {
    notebooks,
    activeNotebook,
    activeId,
    setActiveId,
    isLoading,
    error,
    addNotebook,
    removeNotebook,
    renameNotebook: renameActiveNotebook,
    updateGoal,
  };
}
