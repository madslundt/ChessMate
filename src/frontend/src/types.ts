export type Color = 'white' | 'black';
export type Page = 'play' | 'learn' | 'analyze' | 'history' | 'progress' | 'settings';
export interface User {
  id: string;
  name: string;
  preferences?: Partial<Preferences>;
}
export interface Preferences {
  language: 'en' | 'da';
  coach_language: 'en' | 'da';
  theme: 'light' | 'dark' | 'system';
  player_color: Color;
  difficulty: number;
  orientation: Color | 'player';
  board_theme: 'sage' | 'wood' | 'blue';
  piece_style: 'classic' | 'modern';
  show_legal_moves: boolean;
  show_evaluation_bar: boolean;
  coaching_mode: 'independent' | 'guided' | 'learning' | 'socratic';
  feedback: 'none' | 'short' | 'detailed' | 'mistakes';
  feedback_frequency: 'all' | 'mistakes';
  show_alternatives: boolean;
  hide_best_moves: boolean;
  guided_questions: boolean;
  complexity: 'beginner' | 'intermediate';
  max_explanation_length: number;
  progressive_hints: boolean;
  analysis_time_ms: number;
  analysis_depth: number | null;
  candidate_count: number;
  show_evaluation: boolean;
  show_pv: boolean;
  auto_computer: boolean;
}
export interface Feedback {
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
  mode: 'computer' | 'training' | 'analysis';
  player_color: Color;
  difficulty: number;
  status: string;
  result?: string;
  created_at?: string;
  in_check?: boolean;
  legal_moves?: string[];
  feedback?: Feedback;
}
export interface Candidate {
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
  fen: string;
  candidates: Candidate[];
  observations?: Record<string, unknown>;
  phase?: string;
  engine_available?: boolean;
  [key: string]: unknown;
}
export interface ChatMessage {
  role: 'user' | 'assistant';
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
}
export interface Progress {
  games_played: number;
  attempts: number;
  accuracy: number;
  hints_used: number;
  topics: Topic[];
  recommendations: (string | { topic?: string; reason?: string; exercise_id?: string; title?: string })[];
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
  language: 'en',
  coach_language: 'en',
  theme: 'light',
  player_color: 'white',
  difficulty: 2,
  orientation: 'player',
  board_theme: 'sage',
  piece_style: 'classic',
  show_legal_moves: true,
  show_evaluation_bar: false,
  coaching_mode: 'guided',
  feedback: 'short',
  feedback_frequency: 'all',
  show_alternatives: false,
  hide_best_moves: true,
  guided_questions: true,
  complexity: 'beginner',
  max_explanation_length: 180,
  progressive_hints: true,
  analysis_time_ms: 350,
  analysis_depth: null,
  candidate_count: 3,
  show_evaluation: false,
  show_pv: false,
  auto_computer: true,
};
