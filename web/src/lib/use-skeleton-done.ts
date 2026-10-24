"use client";

import { useEffect, useState } from "react";

import { SKELETON_MIN_MS } from "@/lib/opportunities";

/** True once a list's skeleton has been up for `SKELETON_MIN_MS` after it first mounted. */
export function useSkeletonDone(): boolean {
  const [done, setDone] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setDone(true), SKELETON_MIN_MS);
    return () => window.clearTimeout(timer);
  }, []);
  return done;
}
