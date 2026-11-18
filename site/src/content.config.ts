import { defineCollection, z } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        description: z.string().optional(),
        tags: z.array(z.string()).optional(),
        updated: z
          .union([z.string(), z.date()])
          .transform((value) => (value instanceof Date ? value.toISOString().slice(0, 10) : value))
          .optional(),
      }),
    }),
  }),
};
