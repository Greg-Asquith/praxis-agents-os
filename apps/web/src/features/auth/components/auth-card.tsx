// apps/web/src/features/auth/components/auth-card.tsx

import type { ReactNode } from "react"
import { Link } from "@tanstack/react-router"

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

type AuthCardProps = {
  title: string
  description: string
  footer: ReactNode
  children: ReactNode
}

export function AuthCard({ title, description, footer, children }: AuthCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
      <CardFooter className="text-muted-foreground justify-center text-sm">{footer}</CardFooter>
    </Card>
  )
}

export function AuthLink({ to, children }: { to: "/login" | "/register"; children: ReactNode }) {
  return (
    <Link to={to} className="text-foreground font-medium underline-offset-4 hover:underline">
      {children}
    </Link>
  )
}
