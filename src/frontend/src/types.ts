export type Color = "white" | "black";
export type Page =
  "play" | "learn" | "analyze" | "history" | "progress" | "settings";
export interface User {
  id: string;
  name: string;
  preferences?: Partial<Preferences>;
}
export interface Preferences {
  skill_defaults?: boolean;
  deep_analysis_time_ms?: number;
  highlight_threats?: boolean;
  highlight_pieces?: boolean;
  animate_variations?: boolean;
  return_after_playback?: boolean;
  language: "en" | "da";
  coach_language: "en" | "da";
  theme: "light" | "dark" | "system";
  player_color: Color;
  difficulty: number;
  orientation: Color | "player";
  board_theme: "sage" | "wood" | "blue";
  piece_style: "classic" | "modern";
  show_legal_moves: boolean;
  show_evaluation_bar: boolean;
  coaching_mode: "independent" | "guided" | "learning" | "socratic";
  feedback: "none" | "short" | "detailed" | "mistakes";
  feedback_frequency: "all" | "mistakes";
  show_alternatives: boolean;
  hide_best_moves: boolean;
  guided_questions: boolean;
  complexity: "beginner" | "intermediate" | "advanced";
  play_mode?: "automatic" | "coach_first" | "independent";
  explanation_mode?: "text" | "visual" | "both";
  variation_speed_ms?: number;
  visual_arrows?: "automatic" | "on_request";
  max_explanation_length: number;
  progressive_hints: boolean;
  analysis_time_ms: number;
  analysis_depth: number | null;
  candidate_count: number;
  show_evaluation: boolean;
  show_pv: boolean;
  auto_computer: boolean;
}
export interface VisualInsight {
  id: string;
  text: string;
  fen: string;
  evidence_ids?: string[];
  claim_type?: string;
  squares?: string[];
  arrows?: { from: string; to: string; color?: string }[];
}
export interface CoachingVariation {
  id: string;
  label: string;
  base_fen: string;
  moves: string[];
  resulting_fen?: string;
}
export interface VisualCoaching {
  insights?: VisualInsight[];
  variations?: CoachingVariation[];
}
export interface Feedback extends VisualCoaching {
  analysis_mode?: string;
  confidence?: string;
  classification?: string;
  assessment?: string;
  explanation?: string;
  text?: string;
  takeaway?: string;
  consequence?: string;
  alternatives?: Candidate[];
  best?: Candidate;
  played?: Candidate;
  cp_loss?: number;
  best_move?: string;
  [key: string]: unknown;
}
export interface MoveRecord {
  uci: string;
  san: string;
  fen: string;
  feedback?: Feedback | null;
  actor?: string;
  before_fen?: string;
  [key: string]: unknown;
}
export interface Game {
  id: string;
  fen: string;
  initial_fen: string;
  moves: MoveRecord[];
  revision: number;
  mode: "computer" | "training" | "analysis";
  player_color: Color;
  difficulty: number;
  status: string;
  result?: string;
  created_at?: string;
  in_check?: boolean;
  legal_moves?: string[];
  feedback?: Feedback;
}
export interface Candidate extends VisualCoaching {
  strategy?: {
    plan?: string;
    advantages?: string[];
    drawbacks?: string[];
    qualification?: string;
    effects?: VisualInsight[];
  };
  uci: string;
  san: string;
  cp: number | null;
  mate: number | null;
  pv: string[];
  pv_uci?: string[];
  explanation?: string;
  idea?: string;
  depth?: number;
  white_cp?: number | null;
  white_mate?: number | null;
  risk?: string;
  reply?: string;
  similar_to_best?: boolean;
}
export interface Analysis {
  strategic_insights?: VisualInsight[];
  mode?: string;
  confidence?: string;
  fen: string;
  candidates: Candidate[];
  observations?: Record<string, unknown>;
  phase?: string;
  engine_available?: boolean;
  [key: string]: unknown;
}
export interface CoachingState {
  question?: string;
  acknowledgement?: string;
  stage: string;
  discovered_ids: string[];
  mode: string;
  turns?: number;
}
export interface ChatMessage extends VisualCoaching {
  state?: CoachingState;
  ambiguous_moves?: {
    reference: string;
    choices: { uci: string; san: string; from: string; to: string }[];
  }[];
  role: "user" | "assistant";
  content: string;
  fen?: string;
  source?: string;
  fallback_reason?: string;
}
export interface Exercise {
  id: string;
  title: string;
  category: string;
  difficulty: number | string;
  fen: string;
  objective: string;
  tags?: string[];
  explanation?: string;
  description?: string;
  source_game_id?: string;
  move_count?: number;
}
export interface Attempt {
  correct: boolean;
  complete: boolean;
  feedback: string;
  fen?: string;
  reply?: string;
  solution?: string[];
  explanation?: string;
  [key: string]: unknown;
}
export interface Topic {
  topic: string;
  attempts: number;
  correct: number;
  accuracy: number;
  due?: number;
  strength?: string;
  recent_accuracy?: number;
  independent_accuracy?: number;
  mastery?: number;
  suggested_difficulty?: number;
  repeated_mistakes?: number;
  trend?: "improving" | "declining" | "steady";
}
export interface Progress {
  calculation?: {
    attempts: number;
    assessed_plies: number;
    accurate_plies: number;
    accuracy: number | null;
    response_accuracy: number | null;
    final_assessment_accuracy: number | null;
    independent_solves: number;
    hints_used: number;
  };
  observed_skills?: {
    skill: string;
    label: string;
    observations: number;
    correct: number;
    mistakes: number;
    independent: number;
    accuracy: number;
    priority: "practice" | "observe" | "strength";
    sources: Record<string, number>;
  }[];
  transfer?: {
    decisions: number;
    sound_decisions: number;
    qualification: string;
    samples: {
      game_id: string;
      revision: number;
      topic: string;
      move: string;
      san: string;
      fen: string;
      match: string;
      practice_source: string;
      practice_id: string;
      trained_at: string;
      played_at: string;
      classification: string;
      sound: boolean;
      evidence: Record<string, unknown>;
    }[];
  };

  games_played: number;
  due_reviews?: number;
  repeated_mistakes?: {
    exercise_id: string;
    topic: string;
    title: string;
    failures: number;
  }[];
  attempts: number;
  accuracy: number;
  hints_used: number;
  topics: Topic[];
  recommendations: (
    | string
    | { topic?: string; reason?: string; exercise_id?: string; title?: string }
  )[];
  [key: string]: unknown;
}
export interface Review {
  summary?: string;
  positives?: unknown[];
  mistakes?: unknown[];
  topics?: string[];
  [key: string]: unknown;
}
export const defaults: Preferences = {
  language: "en",
  coach_language: "en",
  theme: "light",
  player_color: "white",
  difficulty: 2,
  orientation: "player",
  board_theme: "sage",
  piece_style: "classic",
  show_legal_moves: true,
  show_evaluation_bar: false,
  coaching_mode: "guided",
  feedback: "short",
  feedback_frequency: "all",
  show_alternatives: false,
  hide_best_moves: true,
  guided_questions: true,
  complexity: "beginner",
  max_explanation_length: 180,
  progressive_hints: true,
  analysis_time_ms: 350,
  analysis_depth: null,
  candidate_count: 3,
  show_evaluation: false,
  show_pv: false,
  auto_computer: true,
};
