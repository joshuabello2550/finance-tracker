import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

interface User {
  email: string
  name?: string
  picture?: string
}

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  signIn: () => void
  signOut: () => void
  getAccessToken: () => string | null
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const API_URL = import.meta.env.VITE_API_BASE || ''

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    // Check if user is already authenticated on mount
    const checkAuth = async () => {
      const token = localStorage.getItem('google_access_token')
      const userInfo = localStorage.getItem('google_user_info')

      if (token && userInfo) {
        try {
          // Verify token is still valid
          const response = await fetch('https://www.googleapis.com/oauth2/v1/userinfo', {
            headers: { Authorization: `Bearer ${token}` }
          })

          if (response.ok) {
            setUser(JSON.parse(userInfo))
          } else {
            // Token expired, clear storage
            localStorage.removeItem('google_access_token')
            localStorage.removeItem('google_user_info')
            localStorage.removeItem('google_token_expiry')
          }
        } catch (error) {
          console.error('Auth check failed:', error)
          localStorage.removeItem('google_access_token')
          localStorage.removeItem('google_user_info')
          localStorage.removeItem('google_token_expiry')
        }
      }
      setIsLoading(false)
    }

    // Check for OAuth callback with tokens in URL
    const params = new URLSearchParams(window.location.search)
    const accessToken = params.get('access_token')
    const authError = params.get('auth_error')

    if (authError) {
      console.error('OAuth error:', authError)
      setIsLoading(false)
      // Clean up URL
      window.history.replaceState({}, document.title, window.location.pathname)
    } else if (accessToken) {
      handleOAuthCallback(params)
    } else {
      checkAuth()
    }
  }, [])

  const handleOAuthCallback = (params: URLSearchParams) => {
    try {
      const accessToken = params.get('access_token')
      const expiry = params.get('expiry')
      const userJson = params.get('user')
      const refreshToken = params.get('refresh_token')

      if (!accessToken || !userJson) {
        throw new Error('Missing authentication data')
      }

      const userData = JSON.parse(userJson)

      // Store tokens and user info
      localStorage.setItem('google_access_token', accessToken)
      localStorage.setItem('google_user_info', JSON.stringify(userData))
      if (expiry) {
        localStorage.setItem('google_token_expiry', expiry)
      }

      // Log refresh token for backend use
      if (refreshToken) {
        console.log('🔑 GOOGLE_REFRESH_TOKEN for backend (.env file):')
        console.log(refreshToken)
        console.log('\nAdd this to your .env file:')
        console.log(`GOOGLE_REFRESH_TOKEN="${refreshToken}"`)
      }

      setUser(userData)

      // Clean up URL
      window.history.replaceState({}, document.title, window.location.pathname)
    } catch (error) {
      console.error('OAuth callback failed:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const signIn = () => {
    window.location.href = `${API_URL}/api/auth/google`
  }

  const signOut = () => {
    localStorage.removeItem('google_access_token')
    localStorage.removeItem('google_user_info')
    localStorage.removeItem('google_token_expiry')
    setUser(null)
  }

  const getAccessToken = () => {
    return localStorage.getItem('google_access_token')
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        signIn,
        signOut,
        getAccessToken
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
