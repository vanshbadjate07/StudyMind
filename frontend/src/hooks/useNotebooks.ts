import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createNotebook,
  deleteNotebook,
  listNotebooks,
  setNotebookGoal,
  type GoalType,
  type NotebookRecord,
} from "../lib/api";

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
      setActiveId((current) => {
        if (current !== null && fetched.some((n) => n.id === current)) return current;
        return fetched[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addNotebook = useCallback(async (name?: string) => {
    const notebook = await createNotebook(name);
    setNotebooks((prev) => [notebook, ...prev]);
    setActiveId(notebook.id);
    return notebook;
  }, []);

  const removeNotebook = useCallback(
    async (id: string) => {
      await deleteNotebook(id);
      setNotebooks((prev) => prev.filter((n) => n.id !== id));
      setActiveId((current) => (current === id ? null : current));
    },
    [],
  );

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
    updateGoal,
  };
}
