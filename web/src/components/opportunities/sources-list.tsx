"use client";

import { CaptionsIcon, FileTextIcon, MailIcon, StickyNoteIcon, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { SourceUpload } from "@/components/opportunities/source-upload";
import {
  formatDateTime,
  NO_SOURCES,
  SOURCE_KIND_LABELS,
  withSource,
  type Source,
  type SourceKind,
} from "@/lib/sources";

const KIND_ICONS: Record<SourceKind, LucideIcon> = {
  email: MailIcon,
  note: StickyNoteIcon,
  transcript: CaptionsIcon,
  document: FileTextIcon,
};

/** The Opportunity's Sources, newest first: kind, file name, version, uploader and time
 * (of the latest version). */
export function SourcesList({ sources }: { sources: readonly Source[] }) {
  if (sources.length === 0) {
    return <p className="text-muted-foreground">{NO_SOURCES}</p>;
  }
  return (
    <table className="w-full table-fixed border-collapse text-left">
      <caption className="sr-only">Sources, newest first</caption>
      <thead className="text-label text-muted-foreground">
        <tr className="h-row border-b border-border">
          <th scope="col" className="w-32 pr-2 font-medium">
            Kind
          </th>
          <th scope="col" className="px-2 font-medium">
            File
          </th>
          <th scope="col" className="w-20 px-2 font-medium">
            Version
          </th>
          <th scope="col" className="w-40 px-2 font-medium">
            Added by
          </th>
          <th scope="col" className="w-48 px-2 font-medium">
            Added
          </th>
        </tr>
      </thead>
      <tbody>
        {sources.map((source) => {
          const Icon = KIND_ICONS[source.kind] ?? FileTextIcon;
          return (
            <tr key={source.id} className="h-row border-b border-border">
              <td className="pr-2">
                <span className="inline-flex items-center gap-1.5">
                  <Icon aria-hidden className="size-3.5 text-muted-foreground" />
                  {SOURCE_KIND_LABELS[source.kind] ?? source.kind}
                </span>
              </td>
              <td className="truncate px-2" title={source.filename}>
                {source.filename}
              </td>
              <td className="px-2 text-numeric">v{source.version}</td>
              <td className="truncate px-2">{source.uploaded_by.name}</td>
              <td className="px-2 text-numeric">{formatDateTime(source.uploaded_at)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** The Sources tab's content: the upload area (only when the caller may add Sources; the
 * API decides on every upload) and the list, which takes each added Source as it lands. */
export function SourcesSection({
  opportunityId,
  canAdd,
  initial,
}: {
  opportunityId: string;
  canAdd: boolean;
  initial: readonly Source[];
}) {
  const [sources, setSources] = useState<Source[]>(() => [...initial]);
  return (
    <div className="flex flex-col gap-6">
      {canAdd ? (
        <SourceUpload
          opportunityId={opportunityId}
          onAdded={(source) => setSources((current) => withSource(current, source))}
        />
      ) : null}
      <SourcesList sources={sources} />
    </div>
  );
}
