import { useAuth } from './AuthContext'

export default function TopBar() {
  const { user, isAuthenticated, signIn, signOut } = useAuth()

  return (
    <div className="topbar">
      <div className="topbar-content">
        <div className="topbar-logo">Finance Tracker</div>
        <div className="topbar-auth">
          {isAuthenticated && user ? (
            <div className="topbar-user">
              {user.picture && (
                <img
                  src={user.picture}
                  alt={user.email}
                  className="topbar-avatar"
                />
              )}
              <span className="topbar-email">{user.email}</span>
              <button className="topbar-btn signout" onClick={signOut}>
                Sign Out
              </button>
            </div>
          ) : (
            <button className="topbar-btn signin" onClick={signIn}>
              Sign In with Google
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
