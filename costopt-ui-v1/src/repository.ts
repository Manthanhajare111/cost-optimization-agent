import type { AnalysisRepository, RepositorySnapshot } from "./domain";
import { seedSnapshot } from "./mockData";

const clone = <T,>(value: T): T => structuredClone(value);

export class MockAnalysisRepository implements AnalysisRepository {
  async load(): Promise<RepositorySnapshot> {
    return clone(seedSnapshot);
  }

  async save(_snapshot: RepositorySnapshot): Promise<void> {
    await Promise.resolve();
  }
}

export const analysisRepository: AnalysisRepository = new MockAnalysisRepository();
