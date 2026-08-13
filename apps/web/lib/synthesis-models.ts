import type { FootprintSynthesisModel } from "@public-profile-search/generated-api-client";

export interface SynthesisModelOption {
  value: FootprintSynthesisModel;
  label: string;
  speedLabel: string;
  inputPrice: string;
  outputPrice: string;
}

export const DEFAULT_SYNTHESIS_MODEL: FootprintSynthesisModel =
  "openai/gpt-5.6-luna";

export const SYNTHESIS_MODEL_OPTIONS = [
  {
    value: "openai/gpt-5.6-luna",
    label: "GPT-5.6 Luna",
    speedLabel: "Balanced value",
    inputPrice: "$0.10",
    outputPrice: "$0.60",
  },
  {
    value: "openai/gpt-5.4-nano",
    label: "GPT-5.4 Nano",
    speedLabel: "Fast budget",
    inputPrice: "$0.20",
    outputPrice: "$1.25",
  },
  {
    value: "openai/gpt-5.4-mini",
    label: "GPT-5.4 Mini",
    speedLabel: "Quality",
    inputPrice: "$0.75",
    outputPrice: "$4.50",
  },
  {
    value: "openai/gpt-oss-120b",
    label: "GPT-OSS 120B",
    speedLabel: "Lowest-cost open weight",
    inputPrice: "$0.037",
    outputPrice: "$0.17",
  },
  {
    value: "deepseek/deepseek-v4-flash-0731",
    label: "DeepSeek V4 Flash",
    speedLabel: "Low-cost open weight",
    inputPrice: "$0.08",
    outputPrice: "$0.18",
  },
  {
    value: "qwen/qwen3.5-35b-a3b",
    label: "Qwen3.5 35B-A3B",
    speedLabel: "Balanced open weight",
    inputPrice: "$0.14",
    outputPrice: "$1.00",
  },
  {
    value: "z-ai/glm-5.2",
    label: "GLM 5.2",
    speedLabel: "Open-weight quality",
    inputPrice: "$0.76",
    outputPrice: "$2.42",
  },
] satisfies readonly SynthesisModelOption[];
