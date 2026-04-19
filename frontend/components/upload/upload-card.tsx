"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Dropzone } from "@/components/upload/dropzone";
import { ApiError, createClaim, type IntakePayload } from "@/lib/api";
import { saveIntake } from "@/lib/intake-storage";

const CAUSES = [
  "Water",
  "Fire",
  "Theft",
  "Storm",
  "Impact",
  "Other",
] as const;
type Cause = (typeof CAUSES)[number] | "";

function yesterdayISO(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

export function UploadCard() {
  const router = useRouter();

  const [claimantName, setClaimantName] = useState("");
  const [incidentDate, setIncidentDate] = useState<string>(yesterdayISO);
  const [cause, setCause] = useState<Cause>("");
  const [location, setLocation] = useState("");
  const [video, setVideo] = useState<File | null>(null);
  const [policy, setPolicy] = useState<File | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = useMemo(
    () =>
      !!claimantName.trim() &&
      !!incidentDate &&
      !!cause &&
      !!location.trim() &&
      !!video &&
      !!policy &&
      !submitting,
    [claimantName, incidentDate, cause, location, video, policy, submitting],
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || !video || !policy) return;

    setSubmitting(true);
    setError(null);

    const intake: IntakePayload = {
      claimant_name: claimantName.trim(),
      incident_date: incidentDate,
      cause,
      location: location.trim(),
    };

    const formData = new FormData();
    formData.append("video", video);
    formData.append("policy", policy);
    formData.append("intake", JSON.stringify(intake));

    try {
      const { claim_id } = await createClaim(formData);
      // Stash so the review screen can replay this to /regenerate.
      saveIntake(claim_id, intake);
      router.push(`/claim/${claim_id}/processing`);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Upload failed. Check that the API server is running.";
      setError(msg);
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="w-full self-center rounded-2xl border border-slate-200 bg-white p-8 shadow-card"
    >
      <p className="text-sm font-semibold uppercase tracking-widest text-navy-600">
        Start a claim
      </p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900">
        Upload your video and policy
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        We&rsquo;ll generate the inventory, citations, and FNOL letter for you.
      </p>

      <div className="mt-8 space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="claimant_name">Claimant name</Label>
            <Input
              id="claimant_name"
              value={claimantName}
              onChange={(e) => setClaimantName(e.target.value)}
              placeholder="Full name"
              autoComplete="name"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="incident_date">Incident date</Label>
            <Input
              id="incident_date"
              type="date"
              value={incidentDate}
              onChange={(e) => setIncidentDate(e.target.value)}
              max={new Date().toISOString().slice(0, 10)}
            />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="cause">Cause of damage</Label>
            <Select
              value={cause}
              onValueChange={(v) => setCause(v as Cause)}
            >
              <SelectTrigger id="cause">
                <SelectValue placeholder="Select a cause" />
              </SelectTrigger>
              <SelectContent>
                {CAUSES.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="location">Location</Label>
            <Input
              id="location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Living room"
            />
          </div>
        </div>

        <div className="grid gap-4 pt-2">
          <Dropzone
            label="Damage video"
            hint="MP4 or MOV"
            accept={{
              "video/mp4": [".mp4"],
              "video/quicktime": [".mov"],
            }}
            file={video}
            onChange={setVideo}
            disabled={submitting}
          />
          <Dropzone
            label="Policy PDF"
            hint="PDF"
            accept={{ "application/pdf": [".pdf"] }}
            file={policy}
            onChange={setPolicy}
            disabled={submitting}
          />
        </div>
      </div>

      <Button
        type="submit"
        size="lg"
        disabled={!canSubmit}
        className="mt-8 h-12 w-full bg-navy-600 text-base text-white hover:bg-navy-700 disabled:bg-navy-600/40"
      >
        {submitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Uploading…
          </>
        ) : (
          <>
            Start claim
            <ArrowRight className="h-4 w-4" />
          </>
        )}
      </Button>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </p>
      )}
    </form>
  );
}
