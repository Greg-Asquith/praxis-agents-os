// apps/web/src/lib/api/errors.ts

export type ApiProblem = {
  type?: string
  title?: string
  status?: number
  detail?: string
  message?: string
  [key: string]: unknown
}

export class ApiError extends Error {
  status: number
  problem: ApiProblem | null

  constructor({
    status,
    message,
    problem,
  }: {
    status: number
    message: string
    problem: ApiProblem | null
  }) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.problem = problem
  }
}

export async function parseApiError(response: Response) {
  const problem = await parseProblem(response)
  return new ApiError({
    status: response.status,
    message: problemMessage(problem, response.statusText),
    problem,
  })
}

export function getErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    return error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return "Something went wrong."
}

async function parseProblem(response: Response) {
  const contentType = response.headers.get("content-type") ?? ""
  if (!contentType.includes("application/json")) {
    return null
  }

  try {
    return (await response.json()) as ApiProblem
  } catch {
    return null
  }
}

function problemMessage(problem: ApiProblem | null, fallback: string) {
  return problem?.detail ?? problem?.message ?? problem?.title ?? fallback
}
