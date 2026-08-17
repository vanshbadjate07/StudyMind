import type { GoalType } from "./api";

export const GOAL_LABELS: Record<GoalType, string> = {
  exam: "Exam prep",
  interview: "Interview prep",
  skill: "Learning a skill",
  exploration: "Just exploring",
  custom: "Custom goal",
};
