import { JobExperience } from "@/components/JobExperience";

export default async function SearchJobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <JobExperience jobId={jobId} />;
}

