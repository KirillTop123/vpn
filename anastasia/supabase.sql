-- База записей для сайта Анастасии Губайдулиной (Supabase, бесплатный тариф).
-- Выполнить один раз: Supabase → SQL Editor → вставить этот файл → Run.

create table if not exists public.bookings (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  name        text not null check (char_length(name) between 1 and 80),
  phone       text not null check (char_length(phone) between 5 and 40),
  service     text check (char_length(service) <= 200),
  service_id  text check (char_length(service_id) <= 40),
  length      text check (length in ('', 's', 'm', 'l')),
  wish_date   date,
  wish_time   text check (char_length(wish_time) <= 20),
  comment     text check (char_length(comment) <= 1000),
  price       text check (char_length(price) <= 40),
  source      text check (char_length(source) <= 40),
  status      text not null default 'new' check (status in ('new', 'confirmed', 'done', 'cancelled')),
  admin_note  text check (char_length(admin_note) <= 1000)
);

-- Кто может читать записи: только почты из этого списка (вход в админку через Supabase Auth)
create table if not exists public.admins (email text primary key);
-- ЗАМЕНИТЕ на почту, с которой будете входить в админку:
insert into public.admins (email) values ('ВАША_ПОЧТА@example.com') on conflict do nothing;

alter table public.bookings enable row level security;
alter table public.admins   enable row level security;

-- Посетители сайта: только создать новую заявку (статус «new», без заметок мастера). Читать чужие заявки нельзя.
drop policy if exists "site can insert" on public.bookings;
create policy "site can insert" on public.bookings for insert to anon
  with check (status = 'new' and admin_note is null);

-- Администратор: всё
drop policy if exists "admin all" on public.bookings;
create policy "admin all" on public.bookings for all to authenticated
  using ((auth.jwt() ->> 'email') in (select email from public.admins))
  with check ((auth.jwt() ->> 'email') in (select email from public.admins));

drop policy if exists "admin reads admins" on public.admins;
create policy "admin reads admins" on public.admins for select to authenticated
  using ((auth.jwt() ->> 'email') = email);

create index if not exists bookings_created_idx on public.bookings (created_at desc);
