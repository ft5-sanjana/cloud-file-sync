export type User = {
  id: number;
  email: string;
  name: string;
  storage_quota: number;
  storage_used: number;
  date_joined: string;
};

export type TokenResponse = {
  access: string;
  user: User;
};

export type RegisterResponse = {
  id: number;
  email: string;
  name: string;
};
