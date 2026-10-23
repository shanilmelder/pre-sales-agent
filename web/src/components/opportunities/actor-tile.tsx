import { actorInitials } from "@/lib/overview";
import type { TraceActor } from "@/lib/trace";
import { cn } from "@/lib/utils";

/** A trace actor's initials tile: a rounded square in the primary tint for agents and the
 * system, a circle in the green tint for people. Decorative (`aria-hidden`): the actor's name
 * is always shown beside it. `size` is the tile's edge in px (24 by default). */
export function ActorTile({
  actor,
  size = 24,
  className,
}: {
  actor: Pick<TraceActor, "type" | "name">;
  size?: 22 | 24;
  className?: string;
}) {
  const person = actor.type === "user";
  return (
    <span
      aria-hidden="true"
      data-actor-type={actor.type}
      className={cn(
        "flex shrink-0 items-center justify-center",
        size === 22 ? "size-[22px] text-[10px] leading-none font-semibold" : "size-6 text-label",
        person
          ? "rounded-full bg-resolved-tint text-resolved"
          : "rounded-md bg-primary-tint text-primary-text",
        className,
      )}
    >
      {actorInitials(actor.name)}
    </span>
  );
}
