import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Password is required."),
});

export const registerSchema = z
  .object({
    first_name: z
      .string()
      .min(1, "First name is required.")
      .max(75, "First name is too long."),
    last_name: z.string().max(75, "Last name is too long.").default(""),
    email: z.string().email("Enter a valid email address."),
    password: z
      .string()
      .min(8, "Password must be at least 8 characters.")
      .max(128),
    confirm_password: z.string().min(1, "Please confirm your password."),
  })
  .refine((d) => d.password === d.confirm_password, {
    message: "Passwords do not match.",
    path: ["confirm_password"],
  });

export const profileUpdateSchema = z.object({
  first_name: z
    .string()
    .min(1, "First name is required.")
    .max(75, "First name is too long."),
  last_name: z.string().max(75, "Last name is too long.").default(""),
});

export const changePasswordSchema = z
  .object({
    old_password: z.string().min(1, "Current password is required."),
    new_password: z
      .string()
      .min(8, "New password must be at least 8 characters.")
      .max(128),
    confirm_new_password: z.string().min(1, "Please confirm the new password."),
  })
  .refine((d) => d.new_password === d.confirm_new_password, {
    message: "New passwords do not match.",
    path: ["confirm_new_password"],
  })
  .refine((d) => d.old_password !== d.new_password, {
    message: "New password must be different from the current password.",
    path: ["new_password"],
  });

export const deleteAccountSchema = z.object({
  password: z.string().min(1, "Password is required to delete your account."),
});

export type LoginInput = z.infer<typeof loginSchema>;
export type RegisterInput = z.infer<typeof registerSchema>;
export type ProfileUpdateInput = z.infer<typeof profileUpdateSchema>;
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>;
export type DeleteAccountInput = z.infer<typeof deleteAccountSchema>;
