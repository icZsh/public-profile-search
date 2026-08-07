import { FootprintJobExperience } from "@/components/FootprintJobExperience";

export default async function FootprintJobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <FootprintJobExperience jobId={jobId} />;
}
